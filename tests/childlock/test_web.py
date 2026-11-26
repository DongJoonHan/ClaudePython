"""!
@brief U7 Web 인터페이스 단위 테스트 (SWR-015, DD-02~04, SWD 10장).

포트 0으로 실제 HTTP 서버를 띄우고 http.client로 요청한다.
"""

import http.client
import json
import runpy
import socket
import sys
import threading
from collections.abc import Iterator
from http.server import HTTPServer

import pytest

from childlock import web
from childlock.controller import ChildLockController
from childlock.model import INITIAL_OUTPUT
from tests.childlock.test_validation import valid_raw


@pytest.fixture
def server() -> Iterator[tuple[int, ChildLockController]]:
    """!
    @brief 테스트용 서버를 백그라운드 스레드로 띄운다.
    @return (포트, 제어기)
    """
    controller = ChildLockController()
    httpd = HTTPServer(("127.0.0.1", 0), web.make_handler(controller))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1], controller
    httpd.shutdown()
    httpd.server_close()


def request(
    port: int, method: str, path: str, body: bytes | None = None
) -> tuple[int, bytes, str]:
    """!
    @brief 요청을 보내고 (상태 코드, 본문, Content-Type)을 돌려준다.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body)
    resp = conn.getresponse()
    data = resp.read()
    ctype = resp.getheader("Content-Type", "")
    conn.close()
    return resp.status, data, ctype


def post_tick(port: int, payload: object) -> tuple[int, bytes, str]:
    """!@brief JSON 본문으로 POST /api/tick을 보낸다."""
    return request(port, "POST", "/api/tick", json.dumps(payload).encode())


def raw_request(port: int, data: bytes) -> bytes:
    """!@brief 소켓으로 원시 HTTP 요청을 보내고 응답 앞부분을 돌려준다."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(data)
        return s.recv(4096)


def test_index_page_is_served(server):
    port, _ = server
    status, body, ctype = request(port, "GET", "/")
    assert status == 200
    assert ctype.startswith("text/html")
    assert b"<html" in body


def test_status_returns_current_output(server):
    port, _ = server
    status, body, ctype = request(port, "GET", "/api/status")
    assert status == 200
    assert ctype.startswith("application/json")
    assert json.loads(body) == INITIAL_OUTPUT.to_dict()


def test_tick_then_events(server):
    port, controller = server
    status, body, _ = post_tick(port, {"now_s": 0.0, "snapshot": valid_raw()})
    assert status == 200
    assert json.loads(body)["state"] == "NORMAL"
    assert controller.status().state == "NORMAL"
    status, body, _ = request(port, "GET", "/api/events")
    events = json.loads(body)
    assert status == 200
    assert [e["event_id"] for e in events] == [1]


def test_missing_snapshot_key_means_no_input(server):
    # DD-02
    port, controller = server
    status, _, _ = post_tick(port, {"now_s": 0.0})
    assert status == 200
    assert controller.events() == ()


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"\xff{",  # UTF-8 아님 (DR-17)
        b"[" * 1500 + b"]" * 1500,  # 과도한 중첩 (DR-17)
        b"[1, 2]",  # 객체가 아님
        b'{"snapshot": null}',  # now_s 없음
        b'{"now_s": -0.5}',
        b'{"now_s": 1' + b"0" * 400 + b"}",  # 10^400
        b'{"now_s": "1"}',
    ],
)
def test_bad_tick_requests_are_400(server, body):
    port, controller = server
    status, _, _ = request(port, "POST", "/api/tick", body)
    assert status == 400
    assert controller.events() == ()


def test_non_increasing_now_s_is_400(server):
    port, _ = server
    assert post_tick(port, {"now_s": 1.0})[0] == 200
    assert post_tick(port, {"now_s": 1.0})[0] == 400


def test_body_over_64kib_is_400(server):
    # DD-03
    port, _ = server
    body = b'{"now_s": 1.0, "pad": "' + b"x" * 65_536 + b'"}'
    assert request(port, "POST", "/api/tick", body)[0] == 400


@pytest.mark.parametrize("length", [None, "abc"])
def test_missing_or_bad_content_length_is_400(server, length):
    # DD-03
    port, _ = server
    header = "" if length is None else f"Content-Length: {length}\r\n"
    reply = raw_request(
        port, f"POST /api/tick HTTP/1.0\r\n{header}\r\n".encode()
    )
    assert reply.startswith(b"HTTP/1.0 400")


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/nope"), ("POST", "/api/status")]
)
def test_unknown_routes_are_404(server, method, path):
    port, _ = server
    assert request(port, method, path, b"{}")[0] == 404


def test_serialization_failure_is_500(server, monkeypatch):
    # SWR-015, DD-04, DD-06: 틱은 반영된 뒤 응답만 실패한다
    port, controller = server

    def broken(_payload: object) -> bytes:
        raise TypeError("injected")

    monkeypatch.setattr(web, "_serialize", broken)
    assert post_tick(port, {"now_s": 0.0, "snapshot": valid_raw()})[0] == 500
    assert len(controller.events()) == 1
    assert request(port, "GET", "/api/status")[0] == 500


def test_unexpected_exception_is_500(server, monkeypatch):
    port, controller = server

    def boom(*_args: object) -> None:
        raise RuntimeError("injected")

    monkeypatch.setattr(controller, "tick", boom)
    assert post_tick(port, {"now_s": 0.0})[0] == 500


def test_serve_uses_single_threaded_http_server(monkeypatch):
    calls: list[object] = []

    class FakeServer:
        def __init__(self, address: tuple[str, int], handler: type) -> None:
            calls.append(address)
            calls.append(handler)

        def serve_forever(self) -> None:
            calls.append("served")

    monkeypatch.setattr(web, "HTTPServer", FakeServer)
    web.serve("localhost", 9123)
    assert calls[0] == ("localhost", 9123)
    assert calls[-1] == "served"


def test_main_parses_host_and_port(monkeypatch):
    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(web, "serve", lambda h, p: seen.append((h, p)))
    assert web.main(["--host", "localhost", "--port", "8123"]) == 0
    assert web.main([]) == 0
    assert seen == [("localhost", 8123), ("127.0.0.1", 8000)]


def test_module_entry_point_runs_main(monkeypatch):
    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(web, "serve", lambda h, p: seen.append((h, p)))
    monkeypatch.setattr(sys, "argv", ["childlock", "--port", "8001"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("childlock", run_name="__main__")
    assert exc.value.code == 0
    assert seen == [("127.0.0.1", 8001)]


def test_huge_content_length_digits_is_400(server):
    # CR-02: 4,300자리를 넘는 숫자도 500이 아니라 400
    port, _ = server
    reply = raw_request(
        port,
        b"POST /api/tick HTTP/1.0\r\nContent-Length: "
        + b"0" * 5000
        + b"5\r\n\r\n",
    )
    assert reply.startswith(b"HTTP/1.0 400")


def test_truncated_body_times_out_with_400_and_server_stays_responsive():
    # CR-04: 선언보다 짧은 본문은 제한 시간 뒤 400, 서버는 계속 응답한다
    controller = ChildLockController()
    httpd = HTTPServer(
        ("127.0.0.1", 0), web.make_handler(controller, timeout_s=0.3)
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        reply = raw_request(
            port,
            b"POST /api/tick HTTP/1.0\r\nContent-Length: 100\r\n\r\n0123456789",
        )
        assert reply.startswith(b"HTTP/1.0 400")
        assert request(port, "GET", "/api/status")[0] == 200
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_large_body_still_gets_400(server):
    # CR-05: 수 MB 본문에도 연결 중단이 아니라 400 응답을 받는다
    port, _ = server
    body = b'{"now_s": 1.0, "pad": "' + b"x" * 3_000_000 + b'"}'
    assert request(port, "POST", "/api/tick", body)[0] == 400


def test_oversized_body_closed_early_still_gets_400(server):
    # CR-05: 버리는 도중 클라이언트가 본문 전송을 끝내도(EOF) 400을 보낸다
    port, _ = server
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(b"POST /api/tick HTTP/1.0\r\nContent-Length: 200000\r\n\r\n")
        s.sendall(b"x" * 70_000)
        s.shutdown(socket.SHUT_WR)
        reply = s.recv(4096)
    assert reply.startswith(b"HTTP/1.0 400")


def test_body_shorter_than_declared_is_400_even_if_valid_json(server):
    # DD-07: 선언보다 짧게 보내고 닫은 본문은 형식이 맞아도 400
    port, controller = server
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(b"POST /api/tick HTTP/1.0\r\nContent-Length: 100\r\n\r\n")
        s.sendall(b'{"now_s": 1.0}')
        s.shutdown(socket.SHUT_WR)
        reply = s.recv(4096)
    assert reply.startswith(b"HTTP/1.0 400")
    assert controller.events() == ()
