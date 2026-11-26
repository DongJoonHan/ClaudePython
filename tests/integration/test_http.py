"""!
@brief SWE.5 통합 시험: HTTP(C7)부터 제어기(C6)·기록(C5)까지 연결 검증.
"""

import http.client
import json
import threading
from collections.abc import Iterator
from http.server import HTTPServer

import pytest

from childlock import web
from childlock.controller import ChildLockController

## SWR-011 결정 기록 허용 필드
RECORD_FIELDS = {
    "event_id",
    "now_s",
    "state",
    "lock_left",
    "lock_right",
    "override_left",
    "override_right",
    "input_validity",
    "reason_left",
    "reason_right",
    "priority_reason",
    "warning_code",
}
## SWRS 3.3 출력 필드
OUTPUT_FIELDS = RECORD_FIELDS - {"event_id", "now_s"} | {"reason_code"}


@pytest.fixture
def port() -> Iterator[int]:
    """!@brief 실제 서버를 띄우고 포트를 돌려준다."""
    httpd = HTTPServer(
        ("127.0.0.1", 0), web.make_handler(ChildLockController())
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def call(port: int, method: str, path: str, payload: object = None) -> object:
    """!@brief JSON 요청을 보내고 200 응답 본문을 해석해 돌려준다."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = None if payload is None else json.dumps(payload).encode()
    conn.request(method, path, body=body)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    assert resp.status == 200, (resp.status, data)
    return json.loads(data)


def snapshot(n: int, **changes: object) -> dict[str, object]:
    """!@brief 틱 n의 유효한 스냅샷."""
    snap: dict[str, object] = {
        "timestamp_s": n / 100,
        "vehicle_speed_kph": 0.0,
        "gear": "P",
        "crash_status": "NONE",
        "rear_left_approach_risk": False,
        "rear_right_approach_risk": False,
        "fire_detected": False,
        "overtemperature_detected": False,
        "adult_present": False,
        "isofix_left": False,
        "isofix_right": False,
        "ignition_on": True,
        "sensor_fault": False,
    }
    snap.update(changes)
    return snap


def test_it11_http_drive_scenario_and_status_consistency(port):
    # UC-09, SWR-014·015: 틱 응답, 상태 조회, 기록이 서로 일치
    out = call(
        port, "POST", "/api/tick", {"now_s": 0.01, "snapshot": snapshot(1)}
    )
    assert set(out) == OUTPUT_FIELDS
    assert out["state"] == "NORMAL"
    cmd = {"side": "all", "action": "lock", "source": "mobile_app"}
    out = call(
        port,
        "POST",
        "/api/tick",
        {"now_s": 0.02, "snapshot": snapshot(2, driver_command=cmd)},
    )
    assert (out["lock_left"], out["lock_right"]) == ("LOCK", "LOCK")
    assert call(port, "GET", "/api/status") == out
    events = call(port, "GET", "/api/events")
    assert [e["event_id"] for e in events] == [1, 2]
    assert all(set(e) == RECORD_FIELDS for e in events)
    assert events[-1]["now_s"] == 0.02


def test_it12_http_crash_release_and_signal_loss(port):
    # SWR-007·013 (HTTP 경로)
    call(
        port,
        "POST",
        "/api/tick",
        {"now_s": 0.01, "snapshot": snapshot(1, vehicle_speed_kph=50.0)},
    )
    out = call(
        port,
        "POST",
        "/api/tick",
        {"now_s": 0.02, "snapshot": snapshot(2, crash_status="CONFIRMED")},
    )
    assert (out["lock_left"], out["state"]) == ("RELEASE", "EMERGENCY")
    out = call(port, "POST", "/api/tick", {"now_s": 0.5})
    assert out["state"] == "EMERGENCY"  # 래치는 갱신 지연보다 우선
    assert out["input_validity"] == "STALE"


def test_it13_http_keeps_latest_100_records(port):
    # SWR-012 (HTTP 경로)
    for n in range(1, 102):
        call(
            port,
            "POST",
            "/api/tick",
            {"now_s": n / 100, "snapshot": snapshot(n)},
        )
    events = call(port, "GET", "/api/events")
    assert [e["event_id"] for e in events] == list(range(2, 102))
