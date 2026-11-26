"""!
@brief SWE.6 SW 시스템 시험: STC-F-041 ~ STC-F-080 (시스템테스트명세_ECL.json).

오라클은 SWRS-ECL-001 v1.2와 QA-ECL-001이다. SIL 케이스는 ChildLockController를
직접 호출하고, Web 케이스는 포트 0의 실제 HTTPServer를 데몬 스레드로 띄워
HTTP(http.client 또는 원시 소켓)로만 판정한다. 시각은 1/100 s 정수(cs)로 다뤄
부동소수 누적 오차를 피한다 (cs=10001 -> now_s=100.01).
"""

import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import HTTPServer
from pathlib import Path

import pytest

from childlock import web
from childlock.controller import ChildLockController

# ------------------------------------------------------------------ 공통 입력
## BASE 스냅샷의 차량 필드 (timestamp_s는 틱마다 now_s)
BASE_FIELDS: dict[str, object] = {
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
    "driver_command": None,
}

## 판정 제외 표시
SKIP = "<skip>"

## SWR-019 순위 (priority_reason 계산용, 3.3절: 같은 순위면 reason_left)
RANK = {
    "CRASH_CONFIRMED": 1,
    "INPUT_STALE": 2,
    "APPROACH_RISK_LOCK": 3,
    "OVERRIDE_REQUESTED": 3,
    "SENSOR_FAULT": 4,
    "CRASH_PENDING": 5,
    "IGNITION_OFF": 6,
    "FIRE_RELEASE": 7,
    "OVERTEMPERATURE_RELEASE": 7,
    "ISOFIX_LOCK": 8,
    "AUTO_LOCK_SPEED": 9,
    "ADULT_PRESENT_RELEASE": 10,
    "DRIVER_LOCK": 11,
    "DRIVER_RELEASE": 11,
    "INPUT_INVALID": 12,
    "NO_CHANGE": 12,
}

## 3.3절 출력 필드 11개
OUTPUT_KEYS = {
    "lock_left",
    "lock_right",
    "state",
    "override_left",
    "override_right",
    "input_validity",
    "reason_left",
    "reason_right",
    "priority_reason",
    "reason_code",
    "warning_code",
}

## SWR-011 결정 기록 필드 12개
RECORD_KEYS = {
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

LDL = ("LOCK", "DRIVER_LOCK")
RDR = ("RELEASE", "DRIVER_RELEASE")
LNC = ("LOCK", "NO_CHANGE")
RNC = ("RELEASE", "NO_CHANGE")
LAS = ("LOCK", "AUTO_LOCK_SPEED")
RIG = ("RELEASE", "IGNITION_OFF")
RCC = ("RELEASE", "CRASH_CONFIRMED")


def cmd(side: str, action: str, source: str) -> dict[str, str]:
    """!@brief CMD(side,action,source)."""
    return {"side": side, "action": action, "source": source}


def snap(cs: int, command: dict | None = None, **changes: object) -> dict:
    """!@brief BASE+{changes}(+CMD) 스냅샷, timestamp_s=now_s."""
    s: dict[str, object] = {"timestamp_s": cs / 100, **BASE_FIELDS}
    s.update(changes)
    if command is not None:
        s["driver_command"] = command
    return s


def tk(c: ChildLockController, cs: int, command=None, **changes) -> dict:
    """!@brief 스냅샷 틱 (SIL)."""
    return c.tick(cs / 100, snap(cs, command, **changes)).to_dict()


def tn(c: ChildLockController, cs: int) -> dict:
    """!@brief 입력 없음 틱 (SIL)."""
    return c.tick(cs / 100, None).to_dict()


def chk(
    out: dict,
    left: tuple[str, str],
    right: tuple[str, str],
    *,
    st: str = "NORMAL",
    iv: str = "VALID",
    wc: str = "NONE",
    ovl: object = False,
    ovr: object = False,
    pr: str | None = None,
) -> None:
    """!
    @brief 기대값을 비교한다. 명시하지 않은 항목은 TC 표기 규칙의 기본값
    (OVL=OVR=false, IV=VALID, WC=NONE). SKIP은 판정 제외. PR을 주지 않으면
    SWRS 3.3절대로 두 도어 reason 중 SWR-019 순위가 높은 쪽(동순위면 좌)이다.
    """
    if pr is None:
        if SKIP in (left[1], right[1]):
            pr = SKIP
        else:
            pr = left[1] if RANK[left[1]] <= RANK[right[1]] else right[1]
    exp = {
        "lock_left": left[0],
        "reason_left": left[1],
        "lock_right": right[0],
        "reason_right": right[1],
        "state": st,
        "input_validity": iv,
        "warning_code": wc,
        "override_left": ovl,
        "override_right": ovr,
        "priority_reason": pr,
        "reason_code": pr,
    }
    exp = {k: v for k, v in exp.items() if v != SKIP}
    assert {k: out[k] for k in exp} == exp


# ------------------------------------------------------------------ Web 보조
@pytest.fixture
def port() -> Iterator[int]:
    """!@brief 새 Web 시뮬레이터 서버(프로세스 시작 직후 상태)의 포트."""
    controller = ChildLockController()
    httpd = HTTPServer(("127.0.0.1", 0), web.make_handler(controller))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def request(
    p: int, method: str, path: str, body: bytes | None = None
) -> tuple[int, bytes]:
    """!@brief http.client 요청 -> (상태 코드, 본문)."""
    conn = http.client.HTTPConnection("127.0.0.1", p, timeout=30)
    conn.request(method, path, body=body)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def get_json(p: int, path: str) -> object:
    """!@brief GET 후 200을 확인하고 JSON을 돌려준다."""
    code, data = request(p, "GET", path)
    assert code == 200
    return json.loads(data)


def events(p: int) -> list[dict]:
    """!@brief GET /api/events."""
    return get_json(p, "/api/events")


def status(p: int) -> dict:
    """!@brief GET /api/status."""
    return get_json(p, "/api/status")


def tick(p: int, now: float, s: object) -> tuple[int, dict | None]:
    """!@brief POST /api/tick {now_s, snapshot}."""
    body = json.dumps({"now_s": now, "snapshot": s}).encode()
    code, data = request(p, "POST", "/api/tick", body)
    return code, (json.loads(data) if code == 200 else None)


def wtick(p: int, cs: int, command=None, **changes) -> dict:
    """!@brief tick(cs, BASE+...) 후 200 확인."""
    code, out = tick(p, cs / 100, snap(cs, command, **changes))
    assert code == 200
    return out


def wnone(p: int, cs: int) -> dict:
    """!@brief tick(cs, null) 후 200 확인."""
    code, out = tick(p, cs / 100, None)
    assert code == 200
    return out


def status_of(resp: bytes) -> int | None:
    """!@brief 응답 바이트의 상태 줄에서 코드를 뽑는다 (없으면 None)."""
    if not resp.startswith(b"HTTP/"):
        return None
    return int(resp.split(b" ", 2)[1])


def raw(p: int, data: bytes, shut_wr: bool = False) -> int | None:
    """!
    @brief 원시 HTTP 요청을 한 번에 보내고 응답 상태 코드를 돌려준다.
    응답 없음·연결 리셋이면 None.
    """
    chunks: list[bytes] = []
    with socket.create_connection(("127.0.0.1", p), timeout=30) as s:
        s.sendall(data)
        if shut_wr:
            s.shutdown(socket.SHUT_WR)
        try:
            while True:
                b = s.recv(65536)
                if not b:
                    break
                chunks.append(b)
        except OSError:
            pass
    return status_of(b"".join(chunks))


def post_raw(p: int, body: bytes, length: str | None = "auto") -> int | None:
    """!
    @brief POST /api/tick 원시 요청. length="auto"면 실제 본문 길이,
    None이면 Content-Length 헤더 없이 본문을 보내고 쓰기를 닫는다.
    """
    head = b"POST /api/tick HTTP/1.0\r\n"
    if length == "auto":
        head += f"Content-Length: {len(body)}\r\n".encode()
    elif length is not None:
        head += f"Content-Length: {length}\r\n".encode()
    return raw(p, head + b"\r\n" + body, shut_wr=length is None)


def tick_body(now: float, s: object = None) -> bytes:
    """!@brief 정상 tick 본문 JSON 바이트."""
    return json.dumps({"now_s": now, "snapshot": s}).encode()


def post_streaming(
    p: int, total: int, prefix: bytes
) -> tuple[int | None, float]:
    """!
    @brief 큰 본문을 별도 스레드로 보내면서 응답 상태 줄을 읽는다.

    서버가 8 MiB만 읽고 연결을 닫으면 전송이 끊기는데, 이때도 이미 받은
    상태 줄을 쓴다 (STC-F-062 절차). 리셋 전에 응답을 확실히 받도록 수신은
    차단(blocking) 모드로 미리 걸어 두고, 30 s 감시 타이머로 무한 대기를 막는다.
    @return (상태 코드, 응답까지 걸린 시간 s)
    """
    s = socket.create_connection(("127.0.0.1", p))
    s.settimeout(None)
    head = f"POST /api/tick HTTP/1.0\r\nContent-Length: {total}\r\n\r\n"

    def sender() -> None:
        try:
            s.sendall(head.encode() + prefix)
            remaining = total - len(prefix)
            chunk = b" " * 65536
            while remaining > 0:
                n = min(remaining, len(chunk))
                s.sendall(chunk[:n])
                remaining -= n
        except OSError:
            pass

    watchdog = threading.Timer(30, s.close)
    watchdog.start()
    start = time.monotonic()
    th = threading.Thread(target=sender, daemon=True)
    th.start()
    data = b""
    try:
        while b"\r\n" not in data:
            b = s.recv(4096)
            if not b:
                break
            data += b
    except OSError:
        pass
    elapsed = time.monotonic() - start
    watchdog.cancel()
    s.close()
    th.join(30)
    return status_of(data), elapsed


# ================================================================== SIL
def test_stc_f_041_stateful_release_then_other_rule_reapplies():
    """!@brief STC-F-041: 화재 FALSE 뒤 자동 잠금 재적용 / 다른 규칙 없으면
    RELEASE 유지 (SWR-017, SWR-003, SWR-019)."""
    fire = ("RELEASE", "FIRE_RELEASE")
    # Step 1
    c = ChildLockController()
    chk(tk(c, 10000, vehicle_speed_kph=5.0), LAS, LAS)
    for cs in (10001, 10002):
        chk(tk(c, cs, vehicle_speed_kph=5.0, fire_detected=True), fire, fire)
    chk(tk(c, 10003, vehicle_speed_kph=5.0), LAS, LAS)
    chk(tk(c, 10004, vehicle_speed_kph=0.0), LNC, LNC)
    # Step 2
    c = ChildLockController()
    out = tk(c, 10000, cmd("all", "lock", "physical_button"))
    assert (out["lock_left"], out["lock_right"]) == ("LOCK", "LOCK")
    chk(tk(c, 10001, fire_detected=True), fire, fire)
    chk(tk(c, 10002), RNC, RNC)
    chk(tk(c, 10003, cmd("all", "lock", "avn")), LDL, LDL)


def test_stc_f_042_forced_release_reason_priority():
    """!@brief STC-F-042: 강제 해제 이유 코드 FIRE > OVERTEMPERATURE >
    ADULT_PRESENT 선택과 단계적 하강 (SWR-017)."""
    c = ChildLockController()
    lk = cmd("all", "lock", "physical_button")
    out = tk(c, 10000, lk)
    assert (out["lock_left"], out["lock_right"]) == ("LOCK", "LOCK")
    fire = ("RELEASE", "FIRE_RELEASE")
    ovt = ("RELEASE", "OVERTEMPERATURE_RELEASE")
    adult = ("RELEASE", "ADULT_PRESENT_RELEASE")
    chk(tk(c, 10001, fire_detected=True), fire, fire)
    chk(tk(c, 10002, lk), LDL, LDL)
    chk(tk(c, 10003, overtemperature_detected=True), ovt, ovt)
    chk(tk(c, 10004, lk), LDL, LDL)
    chk(tk(c, 10005, adult_present=True), adult, adult)
    chk(tk(c, 10006, lk), LDL, LDL)
    out = tk(
        c,
        10007,
        fire_detected=True,
        overtemperature_detected=True,
        adult_present=True,
    )
    chk(out, fire, fire)
    out = tk(c, 10008, overtemperature_detected=True, adult_present=True)
    chk(out, ovt, ovt)
    chk(tk(c, 10009, adult_present=True), adult, adult)
    chk(tk(c, 10010), RNC, RNC)


def test_stc_f_043_isofix_forced_lock_per_door():
    """!@brief STC-F-043: ISOFIX 강제 잠금의 도어 대칭, 상태형 유지, 양쪽
    TRUE에서 unlock 거절 (SWR-018)."""
    c = ChildLockController()
    tk(c, 10000)
    iso = ("LOCK", "ISOFIX_LOCK")
    chk(tk(c, 10001, isofix_left=True), iso, RNC, pr="ISOFIX_LOCK")
    chk(tk(c, 10002), LNC, RNC)
    chk(tk(c, 10003, cmd("left", "unlock", "avn")), RDR, RNC)
    chk(tk(c, 10004, isofix_right=True), RNC, iso)
    chk(tk(c, 10005), RNC, LNC)
    out = tk(
        c,
        10006,
        cmd("all", "unlock", "avn"),
        isofix_left=True,
        isofix_right=True,
    )
    chk(out, iso, iso, pr="ISOFIX_LOCK")
    chk(tk(c, 10007, cmd("all", "unlock", "avn")), RDR, RDR)


def test_stc_f_044_sensor_fault_suppression_and_recovery():
    """!@brief STC-F-044: 센서 고장 중 억제된 규칙의 복구 틱 적용과 이중 고장
    조합 (SWR-021, 003, 004, 017, 018, 005, 007)."""
    # Step 1
    c = ChildLockController()
    tk(c, 10000)
    sf = ("RELEASE", "SENSOR_FAULT")
    fault = {"st": "FAULT", "wc": "SENSOR_FAULT"}
    chk(tk(c, 10001, sensor_fault=True), sf, sf, **fault)
    chk(tk(c, 10002, sensor_fault=True, vehicle_speed_kph=5.0), sf, sf, **fault)
    out = tk(c, 10003, cmd("all", "lock", "avn"), sensor_fault=True)
    chk(out, sf, sf, **fault)
    out = tk(c, 10004, sensor_fault=True, isofix_left=True, isofix_right=True)
    chk(out, sf, sf, **fault)
    out = tk(c, 10005, vehicle_speed_kph=5.0, isofix_left=True)
    chk(out, ("LOCK", "ISOFIX_LOCK"), LAS, pr="ISOFIX_LOCK")
    # Step 2
    c = ChildLockController()
    tk(c, 10000, cmd("all", "lock", "physical_button"))
    lsf = ("LOCK", "SENSOR_FAULT")
    chk(tk(c, 10001, sensor_fault=True), lsf, lsf, **fault)
    chk(tk(c, 10002, sensor_fault=True, fire_detected=True), lsf, lsf, **fault)
    out = tk(c, 10003, sensor_fault=True, fire_detected=True, ignition_on=False)
    chk(out, lsf, lsf, **fault)
    out = tk(
        c,
        10004,
        sensor_fault=True,
        fire_detected=True,
        rear_left_approach_risk=True,
    )
    # TC 정정: TC는 100.04의 WC를 적지 않아 표기 규칙상 기본값 NONE이 되지만,
    # SWRS 3.3절 "warning_code: sensor_fault 유효값이 TRUE이면 state와 관계없이
    # SENSOR_FAULT"이므로 WC=SENSOR_FAULT가 맞다.
    chk(out, ("LOCK", "APPROACH_RISK_LOCK"), lsf, **fault)
    out = tk(c, 10005, fire_detected=True, rear_left_approach_risk=True)
    chk(out, ("LOCK", "APPROACH_RISK_LOCK"), ("RELEASE", "FIRE_RELEASE"))
    out = tk(c, 10006, sensor_fault=True, crash_status="CONFIRMED")
    chk(out, RCC, RCC, st="EMERGENCY", wc="SENSOR_FAULT")


def test_stc_f_045_ignition_off_release():
    """!@brief STC-F-045: 시작 상태, 시동 꺼짐 해제와 lock 무시, 복귀 시 LOCK
    미복원, ISOFIX 재잠금 (SWR-020, 018, 004, 014)."""
    # Step 1
    c = ChildLockController()
    chk(c.status().to_dict(), RIG, RIG, st="OFF")
    chk(tk(c, 10000, ignition_on=False), RIG, RIG, st="OFF")
    chk(tk(c, 10001), RNC, RNC)
    # Step 2
    c = ChildLockController()
    chk(tk(c, 10000, cmd("all", "lock", "physical_button")), LDL, LDL)
    out = tk(c, 10001, cmd("all", "lock", "voice"), ignition_on=False)
    chk(out, RIG, RIG, st="OFF", pr="IGNITION_OFF")
    chk(tk(c, 10002), RNC, RNC)
    # Step 3
    c = ChildLockController()
    iso = ("LOCK", "ISOFIX_LOCK")
    chk(tk(c, 10000, isofix_left=True), iso, RNC)
    chk(tk(c, 10001, isofix_left=True, ignition_on=False), RIG, RIG, st="OFF")
    chk(tk(c, 10002, isofix_left=True), iso, RNC)


def test_stc_f_046_stale_without_any_snapshot_from_start():
    """!@brief STC-F-046: 스냅샷이 한 번도 없어도 0.200 s 정각까지 OFF,
    0.210 s에 DEGRADED (SWR-020, 013, 010)."""
    c = ChildLockController()
    for cs in range(10000, 10021):
        chk(tn(c, cs), RIG, RIG, st="OFF")
    stale = ("RELEASE", "INPUT_STALE")
    chk(tn(c, 10021), stale, stale, st="DEGRADED", iv="STALE")
    chk(tk(c, 10022), RNC, RNC)


def _state_expect(out: dict, st: str, wc: str = "NONE") -> None:
    """!@brief STC-F-047 상태별 기대 reason (모든 lock RELEASE)."""
    reason = {
        "OFF": "IGNITION_OFF",
        "NORMAL": "NO_CHANGE",
        "FAULT": "SENSOR_FAULT",
        "DEGRADED": "INPUT_STALE",
    }[st]
    iv = "STALE" if st == "DEGRADED" else "VALID"
    door = ("RELEASE", reason)
    chk(out, door, door, st=st, iv=iv, wc=wc)


def test_stc_f_047_state_table_all_transitions():
    """!@brief STC-F-047: OFF/NORMAL/FAULT/DEGRADED 사이 모든 전이와 결정표
    행 우선순위 (SWR-013, 020, 021)."""
    c = ChildLockController()
    sf = "SENSOR_FAULT"
    _state_expect(tk(c, 10000, ignition_on=False), "OFF")
    _state_expect(tk(c, 10001), "NORMAL")
    _state_expect(tk(c, 10002, sensor_fault=True), "FAULT", sf)
    out = tk(c, 10003, sensor_fault=True, ignition_on=False)
    _state_expect(out, "FAULT", sf)
    _state_expect(tk(c, 10004, ignition_on=False), "OFF")
    out = tk(c, 10005, sensor_fault=True, ignition_on=False)
    _state_expect(out, "FAULT", sf)
    _state_expect(tk(c, 10006), "NORMAL")
    for cs in range(10007, 10027):
        _state_expect(tn(c, cs), "NORMAL")
    _state_expect(tn(c, 10027), "DEGRADED")
    _state_expect(tk(c, 10028, sensor_fault=True), "FAULT", sf)
    for cs in range(10029, 10049):
        _state_expect(tn(c, cs), "FAULT", sf)
    # TC 정정: TC는 DEGRADED 틱의 WC를 적지 않아 기본값 NONE이 되지만,
    # sensor_fault 유효값은 100.28 이후 TRUE로 남아 있다. SWR-021 "state가
    # EMERGENCY나 DEGRADED여서 FAULT가 아니어도, sensor_fault 유효값이 TRUE이면
    # warning_code=SENSOR_FAULT"이므로 100.49의 WC=SENSOR_FAULT.
    _state_expect(tn(c, 10049), "DEGRADED", sf)
    _state_expect(tk(c, 10050), "NORMAL")
    _state_expect(tk(c, 10051, ignition_on=False), "OFF")
    for cs in range(10052, 10072):
        _state_expect(tn(c, cs), "OFF")
    _state_expect(tn(c, 10072), "DEGRADED")
    _state_expect(tk(c, 10073, ignition_on=False), "OFF")


def test_stc_f_048_emergency_entry_and_latch_release_branches():
    """!@brief STC-F-048: 각 state에서의 EMERGENCY 진입, 래치 해제 틱의
    FAULT/DEGRADED 분기, NORMAL 직접 복귀 불가 (SWR-007, 013, 020, 021)."""
    em = {"st": "EMERGENCY"}
    # Step 1
    c1 = ChildLockController()
    tk(c1, 10000)
    chk(tk(c1, 10001, crash_status="CONFIRMED"), RCC, RCC, **em)
    # Step 2
    c = ChildLockController()
    tk(c, 10000, sensor_fault=True)
    out = tk(c, 10001, sensor_fault=True, crash_status="CONFIRMED")
    chk(out, RCC, RCC, wc="SENSOR_FAULT", **em)
    # Step 3
    c = ChildLockController()
    tk(c, 10000)
    for cs in range(10001, 10022):
        tn(c, cs)
    assert c.status().state == "DEGRADED"
    chk(tk(c, 10022, crash_status="CONFIRMED"), RCC, RCC, **em)
    # Step 4
    c = ChildLockController()
    tk(c, 10000, ignition_on=False)
    out = tk(c, 10001, ignition_on=False, crash_status="CONFIRMED")
    chk(out, RCC, RCC, **em)
    # Step 5
    c = ChildLockController()
    tk(c, 10000)
    assert tk(c, 10001, crash_status="CONFIRMED")["state"] == "EMERGENCY"
    for cs in range(10002, 10102):
        assert tk(c, cs, ignition_on=False)["state"] == "EMERGENCY"
    out = tk(c, 10102, ignition_on=False, sensor_fault=True)
    sf = ("RELEASE", "SENSOR_FAULT")
    chk(out, sf, sf, st="FAULT", wc="SENSOR_FAULT")
    # Step 6
    c = ChildLockController()
    tk(c, 10000)
    tk(c, 10001, crash_status="CONFIRMED")
    for cs in range(10002, 10102):
        out = tk(c, cs, ignition_on=False, overtemperature_detected="x")
        assert out["state"] == "EMERGENCY"
    out = tk(c, 10102, ignition_on=False, overtemperature_detected="x")
    stale = ("RELEASE", "INPUT_STALE")
    chk(out, stale, stale, st="DEGRADED", iv="STALE")
    # Step 7 (Step 1 인스턴스에서 이어서)
    for cs in range(10002, 10301):
        out = tk(c1, cs)
        assert out["state"] == "EMERGENCY"
        assert (out["lock_left"], out["lock_right"]) == ("RELEASE", "RELEASE")


def _scenario_049_input(cs: int) -> tuple[dict | None, dict]:
    """!@brief STC-F-049 절차 표의 틱별 입력 (명령, 변경 필드)."""
    commands = {
        10010: cmd("all", "lock", "physical_button"),
        10600: cmd("all", "unlock", "avn"),
        10750: cmd("all", "unlock", "voice"),
        10850: cmd("right", "unlock", "voice"),
        11002: cmd("right", "unlock", "mobile_app"),
    }
    if 10100 <= cs <= 10500:
        changes: dict = {"vehicle_speed_kph": 5.0, "gear": "D"}
    elif 10700 <= cs <= 11000:
        changes = {"rear_right_approach_risk": True}
    elif cs >= 11050:
        changes = {"ignition_on": False}
    else:
        changes = {}
    return commands.get(cs), changes


def test_stc_f_049_driver_daily_scenario():
    """!@brief STC-F-049: 운전자 일상 시나리오의 reason 순차 전환과 도어 독립,
    override 잔류 (SWR-001, 002, 003, 005, 006, 009, 020)."""
    c = ChildLockController()
    outs: dict[int, dict] = {}
    for cs in range(10000, 11051):
        command, changes = _scenario_049_input(cs)
        outs[cs] = tk(c, cs, command, **changes)
    chk(outs[10010], LDL, LDL)
    chk(outs[10100], LAS, LAS)
    chk(outs[10501], LNC, LNC)
    chk(outs[10600], RDR, RDR)
    arl = ("LOCK", "APPROACH_RISK_LOCK")
    chk(outs[10700], RNC, arl)
    chk(outs[10750], RDR, arl)
    chk(outs[10850], RNC, ("LOCK", "OVERRIDE_REQUESTED"), ovr=True)
    for cs in range(10851, 11001):
        # 우측 reason과 PR은 판정 제외 [TQ-12]
        chk(outs[cs], RNC, ("LOCK", SKIP), ovr=True, pr=SKIP)
    chk(outs[11001], RNC, LNC)
    chk(outs[11002], RNC, RDR)
    chk(outs[11050], RIG, RIG, st="OFF")


def _scenario_050_input(cs: int) -> dict:
    """!@brief STC-F-050 절차 표의 틱별 변경 필드."""
    if cs <= 11000:
        return {"vehicle_speed_kph": 50.0, "gear": "D"}
    if cs <= 11010:
        return {
            "vehicle_speed_kph": 50.0,
            "gear": "D",
            "crash_status": "PENDING",
        }
    if cs == 11011:
        return {
            "vehicle_speed_kph": 20.0,
            "gear": "D",
            "crash_status": "CONFIRMED",
        }
    if 11201 <= cs <= 11349:
        return {"ignition_on": False}
    if cs == 11400:
        return {"vehicle_speed_kph": 5.0, "gear": "D"}
    return {}


def _expect_050(cs: int, out: dict) -> None:
    """!@brief STC-F-050 구간별 기대값."""
    if cs <= 11000:
        chk(out, LAS, LAS)
    elif cs <= 11010:
        pend = ("LOCK", "CRASH_PENDING")
        chk(out, pend, pend)
    elif cs <= 11300:
        chk(out, RCC, RCC, st="EMERGENCY")
    elif cs <= 11349:
        chk(out, RIG, RIG, st="OFF")
    elif cs == 11350:
        chk(out, RNC, RNC)
    elif cs == 11400:
        chk(out, LAS, LAS)


def test_stc_f_050_crash_accident_scenario():
    """!@brief STC-F-050: 충돌 사고 시나리오(자동 잠금 -> PENDING -> CONFIRMED
    -> IGN OFF 1.0 s 래치 해제 -> 재주행) 전 구간 (SWR-003, 007, 008, 020)."""
    c = ChildLockController()
    for cs in range(10000, 11401):
        out = tk(c, cs, **_scenario_050_input(cs))
        _expect_050(cs, out)


# ================================================================== Web
def test_stc_f_051_record_generation_rules(port):
    """!@brief STC-F-051: 스냅샷 N건 -> 기록 N건, 입력 없는 틱은 lock/override/
    state가 바뀔 때만 기록, event_id 연속 (SWR-010, 013)."""
    assert events(port) == []
    wtick(port, 10000, cmd("all", "lock", "physical_button"))
    for cs in range(10001, 10005):
        wtick(port, cs)
    assert [e["event_id"] for e in events(port)] == [1, 2, 3, 4, 5]
    for cs in range(10005, 10025):
        wnone(port, cs)
    assert len(events(port)) == 5
    wnone(port, 10025)
    ev = events(port)
    assert len(ev) == 6
    last = ev[-1]
    assert (last["event_id"], last["now_s"], last["state"]) == (
        6,
        100.25,
        "DEGRADED",
    )
    assert (last["lock_left"], last["lock_right"]) == ("LOCK", "LOCK")
    for cs in range(10026, 10051):
        wnone(port, cs)
    assert len(events(port)) == 6
    wtick(port, 10051)
    ev = events(port)
    assert (len(ev), ev[-1]["event_id"], ev[-1]["state"]) == (7, 7, "NORMAL")
    out52 = wtick(port, 10052, vehicle_speed_kph="x")
    ev = events(port)
    assert (len(ev), ev[-1]["event_id"]) == (8, 8)
    assert ev[-1]["input_validity"] == "INVALID"
    out53 = wnone(port, 10053)
    assert (out53["reason_left"], out53["reason_right"]) == (
        "NO_CHANGE",
        "NO_CHANGE",
    )
    assert out53["input_validity"] == "VALID"
    keys = ("lock_left", "lock_right", "override_left", "override_right")
    assert {k: out53[k] for k in (*keys, "state")} == {
        k: out52[k] for k in (*keys, "state")
    }
    assert out52["input_validity"] != out53["input_validity"]
    assert [e["event_id"] for e in events(port)] == list(range(1, 9))


def test_stc_f_052_latch_release_on_no_input_tick_is_recorded(port):
    """!@brief STC-F-052: 입력 없는 틱에서 EMERGENCY 래치가 풀리면 그 틱에
    기록 1건 (SWR-010, 007)."""
    wtick(port, 10000, cmd("all", "lock", "physical_button"))
    wtick(port, 10001, crash_status="CONFIRMED")
    assert [e["event_id"] for e in events(port)] == [1, 2]
    snap_ticks = {10010 + 7 * k for k in range(15)}
    for cs in range(10002, 10110):
        if cs in snap_ticks:
            out = wtick(port, cs, ignition_on=False)
        else:
            out = wnone(port, cs)
        assert out["state"] == "EMERGENCY"
    chk(wnone(port, 10110), RIG, RIG, st="OFF")
    ev = events(port)
    assert len(ev) == 18
    assert [e["event_id"] for e in ev] == list(range(1, 19))
    assert [round(e["now_s"] * 100) for e in ev[2:17]] == sorted(snap_ticks)
    assert all(e["state"] == "EMERGENCY" for e in ev[2:17])
    last = ev[-1]
    assert last["event_id"] == 18
    assert last["now_s"] == 101.10
    assert last["state"] == "OFF"
    assert (last["lock_left"], last["lock_right"]) == ("RELEASE", "RELEASE")
    assert last["reason_left"] == "IGNITION_OFF"


def test_stc_f_053_record_schema_exact_fields(port):
    """!@brief STC-F-053: 결정 기록 필드 집합이 허용 12개와 정확히 같고 원본
    입력·source가 새지 않음 (SWR-011, 014)."""
    wtick(port, 10000, cmd("all", "lock", "voice"))
    wtick(port, 10001, cmd("front", "lock", "avn"))
    wtick(port, 10002, vehicle_speed_kph="x")
    # 참고: 100.02의 차속은 오류 필드라 차속 유효값의 마지막 갱신은 100.01이고
    # DEGRADED 진입은 TC 절차 주석의 100.23이 아니라 100.22이다 (SWR-013
    # "그 필드가 유효하면 갱신"). 기대값(총 5건)에는 영향이 없다.
    for cs in range(10003, 10024):
        wnone(port, cs)
    wtick(port, 10030, crash_status="CONFIRMED")
    code, body = request(port, "GET", "/api/events")
    assert code == 200
    ev = json.loads(body)
    assert len(ev) == 5
    for rec in ev:
        assert set(rec) == RECORD_KEYS
    text = body.decode("utf-8")
    for word in (
        "source",
        "driver_command",
        "timestamp_s",
        "vehicle_speed_kph",
        "voice",
        "avn",
        "reason_code",
        "snapshot",
    ):
        assert word not in text
    st = status(port)
    assert set(st) >= OUTPUT_KEYS
    assert st["reason_code"] == st["priority_reason"]


def test_stc_f_054_event_retention_boundary(port):
    """!@brief STC-F-054: 기록 보존 100건 경계 (1~100, 2~101, 151~250)
    (SWR-012, 010)."""
    for cs in range(10000, 10100):
        wtick(port, cs)
    assert [e["event_id"] for e in events(port)] == list(range(1, 101))
    wtick(port, 10100)
    assert [e["event_id"] for e in events(port)] == list(range(2, 102))
    for cs in range(10101, 10250):
        wtick(port, cs)
    assert [e["event_id"] for e in events(port)] == list(range(151, 251))


def _free_port() -> int:
    """!@brief 비어 있는 로컬 포트 번호."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _launch(p: int, cwd: Path, tmp: Path) -> subprocess.Popen:
    """!@brief python -m childlock 서버를 띄우고 수신 대기를 기다린다."""
    env = dict(os.environ)
    env.update(
        PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"),
        PYTHONDONTWRITEBYTECODE="1",
        TMP=str(tmp),
        TEMP=str(tmp),
        TMPDIR=str(tmp),
    )
    proc = subprocess.Popen(  # noqa: S603 - 고정 인자, 시험 대상 프로세스
        [sys.executable, "-m", "childlock", "--port", str(p)],
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # 준비 확인은 TCP 연결이 아니라 실제 HTTP 응답(200)으로 한다.
    # Windows에서는 종료된 이전 프로세스의 리스닝 소켓이 잠시 남아 연결만
    # 성공하고 첫 요청이 리셋될 수 있다 (Jenkins PR-7 #1에서 관측).
    deadline = time.monotonic() + 20
    while True:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", p, timeout=2)
            conn.request("GET", "/api/status")
            ok = conn.getresponse().status == 200
            conn.close()
            if ok:
                return proc
        except OSError:
            pass
        if time.monotonic() > deadline or proc.poll() is not None:
            proc.kill()
            raise TimeoutError(f"childlock 서버가 포트 {p}에서 준비되지 않음")
        time.sleep(0.05)


def _stop(proc: subprocess.Popen) -> None:
    """!@brief 서버 프로세스를 종료한다."""
    proc.terminate()
    proc.wait(10)


def _listing(*dirs: Path) -> set[str]:
    """!@brief 디렉터리 아래 모든 파일 경로 목록."""
    return {str(f) for d in dirs for f in d.rglob("*")}


def test_stc_f_055_restart_is_volatile(tmp_path):
    """!@brief STC-F-055: 프로세스 재시작 후 기록 0건, event_id 1부터, 시작
    상태, 기록 파일 없음 (SWR-012, 010)."""
    # 실제 서버 프로세스(python -m childlock)를 띄운다. 작업 디렉터리와
    # 임시 디렉터리(TMP/TEMP)를 시험 전용 빈 디렉터리로 지정해 파일 목록을
    # 비교한다.
    cwd = tmp_path / "cwd"
    tmp = tmp_path / "tmp"
    cwd.mkdir()
    tmp.mkdir()
    before = _listing(cwd, tmp)
    p = _free_port()
    proc = _launch(p, cwd, tmp)
    try:
        for cs in range(10000, 10030):
            wtick(p, cs, vehicle_speed_kph=5.0)
        assert len(events(p)) == 30
    finally:
        _stop(proc)
    # 재시작은 새 포트로 한다 (이전 리스닝 소켓 잔류와 무관하게 판정)
    p = _free_port()
    proc = _launch(p, cwd, tmp)
    try:
        assert events(p) == []
        st = status(p)
        assert (st["lock_left"], st["lock_right"], st["state"]) == (
            "RELEASE",
            "RELEASE",
            "OFF",
        )
        code, _ = tick(p, 100.00, snap(10000))
        assert code == 200
        ev = events(p)
        assert [e["event_id"] for e in ev] == [1]
        assert ev[0]["now_s"] == 100.00
    finally:
        _stop(proc)
    assert _listing(cwd, tmp) == before


def test_stc_f_056_status_query(port):
    """!@brief STC-F-056: 첫 틱 전 상태, 틱 응답과 상태 조회 일치, 400 요청이
    상태를 바꾸지 않음 (SWR-014, 015)."""
    st = status(port)
    assert set(st) >= OUTPUT_KEYS
    # input_validity·override·warning_code는 키 존재만 확인 [TQ-15]
    chk(st, RIG, RIG, st="OFF", iv=SKIP, wc=SKIP, ovl=SKIP, ovr=SKIP)
    out = wtick(port, 10000, cmd("all", "lock", "physical_button"))
    after = status(port)
    assert {k: after[k] for k in OUTPUT_KEYS} == {
        k: out[k] for k in OUTPUT_KEYS
    }
    chk(out, LDL, LDL, pr="DRIVER_LOCK")
    code, _ = tick(port, 99.0, snap(9900))
    assert code == 400
    assert status(port) == out
    assert len(events(port)) == 1


def _assert_unchanged(p: int, ref: dict, count: int) -> None:
    """!@brief GET /api/status와 기록 건수가 기준과 같은지 확인한다."""
    assert status(p) == ref
    assert len(events(p)) == count


def _speed_token_body(cs: int, token: str) -> bytes:
    """!@brief vehicle_speed_kph 자리에 JSON 토큰을 그대로 넣은 tick 본문."""
    s = snap(cs, vehicle_speed_kph="@@")
    return tick_body(cs / 100, s).replace(b'"@@"', token.encode())


def test_stc_f_057_field_errors_200_vs_parser_limit_400(port):
    """!@brief STC-F-057: snapshot 안의 오류 값은 200+INVALID, 파서 한계를
    넘는 큰 정수는 400이고 틱 미진행 (SWR-015, 013)."""
    wtick(port, 10000)
    inv = ("RELEASE", "INPUT_INVALID")
    # (a) NaN 토큰, (b) 1e999
    for cs, token in ((10001, "NaN"), (10002, "1e999")):
        body = _speed_token_body(cs, token)
        code, data = request(port, "POST", "/api/tick", body)
        assert code == 200
        chk(json.loads(data), inv, inv, iv="INVALID")
    ref, count = status(port), len(events(port))
    # (c) 5001자리 정수: 400 (500 아님), 틱 미진행
    assert post_raw(port, _speed_token_body(10003, "1" + "0" * 5000)) == 400
    _assert_unchanged(port, ref, count)
    # (d) 100.03이 (c)로 소비되지 않음
    out = wnone(port, 10003)
    assert out["input_validity"] == "VALID"
    assert len(events(port)) == count
    # (e) crash_status=7
    out = wtick(port, 10004, crash_status=7)
    assert out["input_validity"] == "INVALID"
    assert out["state"] != "EMERGENCY"


def test_stc_f_058_malformed_body_classes_are_400(port):
    """!@brief STC-F-058: 본문 형식 오류 9종이 모두 400이고 틱 미진행
    (SWR-015)."""
    ref = wtick(port, 10000)
    bodies = [
        b"not json",
        b"[]",
        b'"text"',
        b"null",
        b'{"now_s":100.01,"snapshot":null,"k":"\xff"}',
        b"[" * 30000 + b"]" * 30000,
        b'{"now_s":100.01,"snapshot":null,"big":' + b"9" * 5000 + b"}",
        b'{"now_s":100.01,"snapshot":null',
        b"",
    ]
    for b in bodies:
        assert post_raw(port, b) == 400
        _assert_unchanged(port, ref, 1)
    wtick(port, 10001)
    assert len(events(port)) == 2


def test_stc_f_059_now_s_error_classes_are_400(port):
    """!@brief STC-F-059: now_s 오류 클래스 10종이 모두 400이고 틱 미진행
    (SWR-015, SWRS 2장 SW 시계)."""
    ref = wtick(port, 10000)
    bodies = [
        b'{"snapshot":null}',
        b'{"now_s":"100.5","snapshot":null}',
        b'{"now_s":true,"snapshot":null}',
        b'{"now_s":null,"snapshot":null}',
        b'{"now_s":NaN,"snapshot":null}',
        b'{"now_s":Infinity,"snapshot":null}',
        b'{"now_s":-0.01,"snapshot":null}',
        b'{"now_s":1000000000.000001,"snapshot":null}',
        b'{"now_s":1e400,"snapshot":null}',
        b'{"now_s":[100.5],"snapshot":null}',
    ]
    for b in bodies:
        assert post_raw(port, b) == 400
        _assert_unchanged(port, ref, 1)
    wtick(port, 10001)


def test_stc_f_060_now_s_order_rounding_and_range(port):
    """!@brief STC-F-060: now_s 1 us 반올림 순서·범위 경계 (0, 1e9 정각 허용,
    400 요청은 직전 시각을 바꾸지 않음) (SWR-015, 013)."""
    cases = [
        ("0", 200),
        ("0", 400),
        ("0.0000004", 400),
        ("0.0000006", 200),
        ("0.0000011", 400),
        ("0.000002", 200),
        ("5.0", 200),
        ("4.99", 400),
        ("5.005", 200),
        ("999999999.999999", 200),
        ("1000000000.0", 200),
        ("1000000000.000001", 400),
        ("1000000000.0", 400),
    ]
    for text, expected in cases:
        # now_s와 BASE의 timestamp_s를 같은 리터럴로 보낸다
        s = dict(snap(0), timestamp_s="@@")
        b = tick_body(0, s)
        b = b.replace(b'"now_s": 0,', b'"now_s": ' + text.encode() + b",")
        b = b.replace(b'"@@"', text.encode())
        code, _ = request(port, "POST", "/api/tick", b)
        assert (text, code) == (text, expected)
    assert [e["event_id"] for e in events(port)] == list(range(1, 8))


def _padded(cs: int, size: int) -> bytes:
    """!@brief 정상 tick 본문을 공백으로 size 바이트까지 채운다."""
    b = tick_body(cs / 100, snap(cs))
    return b + b" " * (size - len(b))


def test_stc_f_061_content_length_and_body_size_boundaries(port):
    """!@brief STC-F-061: Content-Length 형식·자릿수와 본문 64 KiB 경계,
    1 MiB 본문 버림 후 400 (SWR-015) [TQ-11]."""
    ref = status(port)
    b0 = tick_body(100.00, snap(10000))
    for length in (None, "abc", "-5", f"{len(b0):011d}"):
        assert post_raw(port, b0, length=length) == 400
        _assert_unchanged(port, ref, 0)
    assert post_raw(port, b0, length=f"{len(b0):010d}") == 200
    assert len(events(port)) == 1
    assert post_raw(port, _padded(10001, 65536)) == 200
    ref = status(port)
    assert len(events(port)) == 2
    assert post_raw(port, _padded(10002, 65537)) == 400
    _assert_unchanged(port, ref, 2)
    assert post_raw(port, _padded(50000, 1024 * 1024)) == 400
    _assert_unchanged(port, ref, 2)
    wtick(port, 10002)
    assert len(events(port)) == 3


def test_stc_f_062_huge_bodies_get_400_and_server_survives(port):
    """!@brief STC-F-062: 8 MiB, 8 MiB+1, 9 MiB 본문에도 400 후 서버 생존
    (SWR-015 '8 MiB까지 읽어서 버린 뒤 응답')."""
    wtick(port, 10000)
    prefix = b'{"now_s": 900.0, "snapshot": null}'
    sizes = (8 * 1024 * 1024, 8 * 1024 * 1024 + 1, 9 * 1024 * 1024)
    for n, size in enumerate(sizes, start=1):
        code, elapsed = post_streaming(port, size, prefix)
        assert code == 400
        assert elapsed < 30  # 시험 가정 상한 [TQ-14]
        assert request(port, "GET", "/api/status")[0] == 200
        wtick(port, 10000 + n)
    assert [round(e["now_s"] * 100) for e in events(port)] == [
        10000,
        10001,
        10002,
        10003,
    ]


def test_stc_f_063_other_methods_are_501(port):
    """!@brief STC-F-063: GET·POST 외 메서드는 501이고 틱·기록·상태 불변
    (SWR-015)."""
    ref = wtick(port, 10000)
    body = b'{"now_s":100.01,"snapshot":null}'
    reqs = [
        ("PUT", "/api/tick", body),
        ("DELETE", "/api/tick", b""),
        ("PATCH", "/api/tick", body),
        ("OPTIONS", "/api/status", b""),
        ("HEAD", "/api/status", b""),
    ]
    for method, path, b in reqs:
        head = f"{method} {path} HTTP/1.0\r\n"
        if b:
            head += f"Content-Length: {len(b)}\r\n"
        assert raw(port, head.encode() + b"\r\n" + b) == 501
        _assert_unchanged(port, ref, 1)
    wtick(port, 10001)


# ================================================================== PICT
def _pw01(
    setup: dict | None,
    prior: tuple[str, str],
    command: dict,
    left: tuple[str, str],
    right: tuple[str, str],
) -> None:
    """!@brief PW-01 공통 절차: 직전 출력 생성 -> 유지 확인 -> 잠금 명령."""
    c = ChildLockController()
    for out in (tk(c, 10000, setup), tk(c, 10001)):
        assert (out["lock_left"], out["lock_right"], out["state"]) == (
            *prior,
            "NORMAL",
        )
    chk(tk(c, 10002, command), left, right, pr="DRIVER_LOCK")


def test_stc_f_064_pw01_voice_all_lock():
    """!@brief STC-F-064: voice/all lock, 직전 좌 LOCK/우 RELEASE
    (SWR-001, 009)."""
    _pw01(
        cmd("left", "lock", "physical_button"),
        ("LOCK", "RELEASE"),
        cmd("all", "lock", "voice"),
        LDL,
        LDL,
    )


def test_stc_f_065_pw01_button_right_lock():
    """!@brief STC-F-065: physical_button/right lock, 직전 좌/우 LOCK
    (SWR-001, 009)."""
    _pw01(
        cmd("all", "lock", "physical_button"),
        ("LOCK", "LOCK"),
        cmd("right", "lock", "physical_button"),
        LNC,
        LDL,
    )


def test_stc_f_066_pw01_button_all_lock():
    """!@brief STC-F-066: physical_button/all lock, 직전 좌 RELEASE/우 LOCK
    (SWR-001, 009)."""
    _pw01(
        cmd("right", "lock", "physical_button"),
        ("RELEASE", "LOCK"),
        cmd("all", "lock", "physical_button"),
        LDL,
        LDL,
    )


def test_stc_f_067_pw01_mobile_left_lock():
    """!@brief STC-F-067: mobile_app/left lock, 직전 좌/우 RELEASE
    (SWR-001, 009)."""
    _pw01(
        None,
        ("RELEASE", "RELEASE"),
        cmd("left", "lock", "mobile_app"),
        LDL,
        RNC,
    )


def test_stc_f_068_pw01_avn_left_lock():
    """!@brief STC-F-068: avn/left lock, 직전 좌/우 LOCK (SWR-001, 009)."""
    _pw01(
        cmd("all", "lock", "physical_button"),
        ("LOCK", "LOCK"),
        cmd("left", "lock", "avn"),
        LDL,
        LNC,
    )


def test_stc_f_069_pw01_voice_right_lock():
    """!@brief STC-F-069: voice/right lock, 직전 좌/우 RELEASE
    (SWR-001, 009)."""
    _pw01(
        None,
        ("RELEASE", "RELEASE"),
        cmd("right", "lock", "voice"),
        RNC,
        LDL,
    )


def test_stc_f_070_pw01_button_left_lock():
    """!@brief STC-F-070: physical_button/left lock, 직전 좌/우 RELEASE
    (SWR-001, 009)."""
    _pw01(
        None,
        ("RELEASE", "RELEASE"),
        cmd("left", "lock", "physical_button"),
        LDL,
        RNC,
    )


def test_stc_f_071_pw01_mobile_all_lock():
    """!@brief STC-F-071: mobile_app/all lock, 직전 좌/우 LOCK
    (SWR-001, 009)."""
    _pw01(
        cmd("all", "lock", "physical_button"),
        ("LOCK", "LOCK"),
        cmd("all", "lock", "mobile_app"),
        LDL,
        LDL,
    )


def test_stc_f_072_pw01_voice_left_lock():
    """!@brief STC-F-072: voice/left lock, 직전 좌/우 LOCK (SWR-001, 009)."""
    _pw01(
        cmd("all", "lock", "physical_button"),
        ("LOCK", "LOCK"),
        cmd("left", "lock", "voice"),
        LDL,
        LNC,
    )


def test_stc_f_073_pw01_mobile_right_lock():
    """!@brief STC-F-073: mobile_app/right lock, 직전 좌 RELEASE/우 LOCK
    (SWR-001, 009)."""
    _pw01(
        cmd("right", "lock", "physical_button"),
        ("RELEASE", "LOCK"),
        cmd("right", "lock", "mobile_app"),
        RNC,
        LDL,
    )


def test_stc_f_074_pw01_avn_all_lock():
    """!@brief STC-F-074: avn/all lock, 직전 좌/우 RELEASE (SWR-001, 009)."""
    _pw01(
        None,
        ("RELEASE", "RELEASE"),
        cmd("all", "lock", "avn"),
        LDL,
        LDL,
    )


def test_stc_f_075_pw01_avn_right_lock():
    """!@brief STC-F-075: avn/right lock, 직전 좌/우 LOCK (SWR-001, 009)."""
    _pw01(
        cmd("all", "lock", "physical_button"),
        ("LOCK", "LOCK"),
        cmd("right", "lock", "avn"),
        LNC,
        LDL,
    )


def _pw02(speed: float, command: dict, right: tuple[str, str]) -> None:
    """!@brief PW-02 공통 절차: 좌/우 LOCK -> 유지 -> 3.0 미만 차속 해제."""
    c = ChildLockController()
    lk = cmd("all", "lock", "physical_button")
    out = tk(c, 10000, lk, vehicle_speed_kph=speed)
    assert (out["lock_left"], out["lock_right"], out["state"]) == (
        "LOCK",
        "LOCK",
        "NORMAL",
    )
    chk(tk(c, 10001, vehicle_speed_kph=speed), LNC, LNC)
    out = tk(c, 10002, command, vehicle_speed_kph=speed)
    chk(out, RDR, right, pr="DRIVER_RELEASE")


def test_stc_f_076_pw02_avn_left_unlock_2_9kph():
    """!@brief STC-F-076: avn/left unlock, 차속 2.9 (SWR-002, 004) [Q-12]."""
    _pw02(2.9, cmd("left", "unlock", "avn"), LNC)


def test_stc_f_077_pw02_mobile_left_unlock_0kph():
    """!@brief STC-F-077: mobile_app/left unlock, 차속 0.0 (SWR-002, 004)
    [Q-12]."""
    _pw02(0.0, cmd("left", "unlock", "mobile_app"), LNC)


def test_stc_f_078_pw02_button_left_unlock_0kph():
    """!@brief STC-F-078: physical_button/left unlock, 차속 0.0
    (SWR-002, 004) [Q-12]."""
    _pw02(0.0, cmd("left", "unlock", "physical_button"), LNC)


def test_stc_f_079_pw02_voice_left_unlock_2_9kph():
    """!@brief STC-F-079: voice/left unlock, 차속 2.9 (SWR-002, 004)
    [Q-12]."""
    _pw02(2.9, cmd("left", "unlock", "voice"), LNC)


def test_stc_f_080_pw02_mobile_all_unlock_2_9kph():
    """!@brief STC-F-080: mobile_app/all unlock, 차속 2.9 (SWR-002, 004)
    [Q-12]."""
    _pw02(2.9, cmd("all", "unlock", "mobile_app"), RDR)
