"""!
@brief C7 Web 인터페이스: HTTP 요청을 제어기 호출로 바꾸고 JSON으로 응답한다.

SWD-ECL-001 10장 (SWR-015, DD-02~04, DD-06). 단일 스레드 HTTPServer를 쓴다
(AD-03). 사전조건 위반(TickRejectedError)과 입력 형식 오류는 400, 그 밖의
모든 예외는 500으로 바꿔 응답 없이 연결이 끊기지 않게 한다.
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources

from childlock.controller import ChildLockController
from childlock.model import (
    MAX_BODY_BYTES,
    MAX_DISCARD_BYTES,
    MAX_LENGTH_DIGITS,
    REQUEST_TIMEOUT_S,
    TickRejectedError,
)

_JSON = "application/json; charset=utf-8"
_HTML = "text/html; charset=utf-8"
## 500 응답 본문은 직렬화 실패와 무관하게 고정 바이트로 보낸다
_INTERNAL_ERROR_BODY = b'{"error": "Internal Server Error"}'


def _serialize(payload: object) -> bytes:
    """!
    @brief 응답 본문을 JSON 바이트로 직렬화한다.
    @param payload JSON으로 바꿀 값
    @return UTF-8 JSON 바이트
    """
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _index_html() -> bytes:
    """!
    @brief 시뮬레이터 화면 파일을 읽는다 (SW 경계 밖 요소, SWA 4.1).
    @return HTML 바이트
    """
    page = resources.files("childlock").joinpath("static/index.html")
    return page.read_bytes()


class _Handler(BaseHTTPRequestHandler):
    """!
    @brief 경로별 요청 처리기.

    제어기는 make_handler가 하위 클래스에 묶는다.
    """

    ## 요청을 처리할 제어기 (make_handler가 지정)
    bound_controller: ChildLockController

    def do_GET(self) -> None:
        """!@brief GET 요청을 처리한다."""
        self._guarded(self._route_get)

    def do_POST(self) -> None:
        """!@brief POST 요청을 처리한다."""
        self._guarded(self._route_post)

    def log_message(self, format: str, *args: object) -> None:
        """!@brief 요청 줄과 상태 코드만 남긴다 (본문은 남기지 않음)."""
        sys.stderr.write(f"{self.address_string()} - {format % args}\n")

    def _guarded(self, route: Callable[[], None]) -> None:
        """!
        @brief 처리 중 예상하지 못한 예외를 500으로 바꾼다 (DD-04).
        @param route 실제 처리 함수
        """
        try:
            route()
        except Exception as exc:  # noqa: BLE001 - DD-04: 모든 예외를 500으로
            sys.stderr.write(f"500 {type(exc).__name__}\n")
            self._send(500, _INTERNAL_ERROR_BODY, _JSON)

    def _route_get(self) -> None:
        """!@brief GET 경로를 나눈다."""
        controller = self.bound_controller
        if self.path == "/":
            self._send(200, _index_html(), _HTML)
        elif self.path == "/api/status":
            self._send_json(controller.status().to_dict())
        elif self.path == "/api/events":
            self._send_json([r.to_dict() for r in controller.events()])
        else:
            self._send_error(404)

    def _route_post(self) -> None:
        """!@brief POST /api/tick을 처리한다 (SWR-015)."""
        if self.path != "/api/tick":
            self._send_error(404)
            return
        body = self._read_json_body()
        if body is None:
            self._send_error(400)
            return
        try:
            # DD-02: snapshot 키가 없으면 입력 없음(None)
            output = self.bound_controller.tick(
                body["now_s"], body.get("snapshot")
            )
        except TickRejectedError:
            self._send_error(400)
            return
        self._send_json(output.to_dict())

    def _read_json_body(self) -> dict[str, object] | None:
        """!
        @brief 본문을 읽어 now_s가 있는 JSON 객체로 해석한다.
        @return 해석한 객체, 형식 오류면 None (DD-03, DD-07, DR-17)
        """
        size = self._content_length()
        if size is None:
            return None
        raw = self._read_body(size)
        if raw is None:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            # JSON·UTF-8 오류(ValueError)와 과도한 중첩은 입력 오류
            return None
        if not isinstance(data, dict) or "now_s" not in data:
            return None
        return data

    def _content_length(self) -> int | None:
        """!
        @brief Content-Length 헤더를 검사한다 (DD-03).
        @return 본문 크기, 없거나 숫자가 아니거나 너무 길면 None
        """
        length = self.headers.get("Content-Length")
        if length is None or not length.isdecimal():
            return None
        if len(length) > MAX_LENGTH_DIGITS:
            # 아주 긴 숫자는 int() 자릿수 제한 전에 거절한다 (CR-02)
            return None
        return int(length)

    def _read_body(self, size: int) -> bytes | None:
        """!
        @brief 본문을 정확히 size 바이트 읽는다.

        상한을 넘으면 상한까지 읽어 버리고 연결을 닫는다(CR-05). 본문이
        선언보다 짧아 제한 시간이 지나면 None이다(DD-07, CR-04).
        @param size 선언된 본문 크기
        @return 본문 바이트 또는 None
        """
        try:
            if size > MAX_BODY_BYTES:
                self.close_connection = True
                self._discard(min(size, MAX_DISCARD_BYTES))
                return None
            raw = self.rfile.read(size)
        except TimeoutError:
            return None
        return raw if len(raw) == size else None

    def _discard(self, size: int) -> None:
        """!
        @brief 본문을 64 KiB씩 읽어서 버린다.
        @param size 버릴 바이트 수
        """
        remaining = size
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, MAX_BODY_BYTES))
            if not chunk:
                break
            remaining -= len(chunk)

    def _send_json(self, payload: object) -> None:
        """!@brief 200 JSON 응답을 보낸다."""
        self._send(200, _serialize(payload), _JSON)

    def _send_error(self, status: int) -> None:
        """!@brief 오류 코드와 사유를 JSON으로 보낸다."""
        phrase = HTTPStatus(status).phrase
        self._send(status, _serialize({"error": phrase}), _JSON)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        """!@brief 상태 줄, 헤더, 본문을 보낸다."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_handler(
    controller: ChildLockController,
    timeout_s: float = REQUEST_TIMEOUT_S,
) -> type[BaseHTTPRequestHandler]:
    """!
    @brief 제어기 하나에 묶인 요청 처리기 클래스를 만든다.
    @param controller 요청을 처리할 제어기
    @param timeout_s 요청 소켓 제한 시간 (DD-07)
    @return BaseHTTPRequestHandler 하위 클래스
    """

    class _BoundHandler(_Handler):
        """!@brief controller에 묶인 처리기."""

        bound_controller = controller
        timeout = timeout_s

    return _BoundHandler


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """!
    @brief 단일 스레드 HTTP 서버로 시뮬레이터를 제공한다 (AD-03).
    @param host 바인드 주소
    @param port 포트
    """
    server = HTTPServer((host, port), make_handler(ChildLockController()))
    server.serve_forever()


def main(argv: Sequence[str] | None = None) -> int:
    """!
    @brief 명령줄 진입점: python -m childlock [--host H] [--port P]
    @param argv 명령줄 인자 (None이면 sys.argv)
    @return 종료 코드
    """
    parser = argparse.ArgumentParser(
        prog="childlock", description="전자식 차일드락 PC/SIL 시뮬레이터"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    serve(args.host, args.port)
    return 0
