"""!
@brief SWE.6 SIL 시험: 시스템 테스트 명세 STC-F-001~040 자동화.

시험 명세: docs/06_swe6_verification/시스템테스트명세_ECL.json.
오라클: SWRS-ECL-001 v1.2, QA-ECL-001.
표기: 시각은 now_s를 1/100 s 정수(cs)로 다룬다 (100.01 s → 10001).
기대값에 쓰지 않은 항목은 OVL=OVR=false, IV=VALID, WC=NONE으로 판정한다
(명세 사전조건 표기 규칙).
"""

import math
from enum import StrEnum

from childlock.controller import ChildLockController
from childlock.model import Output

LOCK = "LOCK"
REL = "RELEASE"

## 명세 사전조건: 기대값에 쓰지 않은 항목의 기본 기대값
_DEFAULTS: dict[str, object] = {
    "input_validity": "VALID",
    "warning_code": "NONE",
    "override_left": False,
    "override_right": False,
}
## check()의 짧은 키워드 → 출력 필드 이름
_ALIAS = {
    "st": "state",
    "iv": "input_validity",
    "wc": "warning_code",
    "ovl": "override_left",
    "ovr": "override_right",
}


def ts(cs: int) -> float:
    """!
    @brief 1/100 s 정수를 now_s(초)로 바꾼다.
    @param cs 1/100 s 단위 시각
    @return now_s
    """
    return cs / 100


def cmd(side: object, action: object, source: object) -> dict[str, object]:
    """!@brief CMD(side, action, source) 표기를 driver_command로 만든다."""
    return {"side": side, "action": action, "source": source}


LOCK_ALL = cmd("all", "lock", "physical_button")


def snap(
    now: float,
    *,
    command: object = None,
    drop: tuple[str, ...] = (),
    **fields: object,
) -> dict[str, object]:
    """!
    @brief BASE 스냅샷에 표기한 변경만 적용한다.
    @param now timestamp_s 기본값 (= now_s)
    @param command driver_command 값
    @param drop 키 자체를 뺄 필드
    @param fields 바꿀 필드
    @return 원시 스냅샷
    """
    raw: dict[str, object] = {
        "timestamp_s": now,
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
        "driver_command": command,
    }
    raw.update(fields)
    for key in drop:
        del raw[key]
    return raw


def send(c: ChildLockController, k: int, **kw: object) -> Output:
    """!@brief now_s=k/100에 BASE+kw 스냅샷 한 건을 보낸다."""
    now = ts(k)
    return c.tick(now, snap(now, **kw))


def idle(c: ChildLockController, first: int, last: int) -> dict[int, Output]:
    """!@brief first~last 틱마다 입력 없이 tick한다."""
    return {k: c.tick(ts(k), None) for k in range(first, last + 1)}


def hold(
    c: ChildLockController,
    first: int,
    last: int,
    cmds: dict[int, dict[str, object]] | None = None,
    **kw: object,
) -> dict[int, Output]:
    """!
    @brief 유지(first~last): 같은 스냅샷을 timestamp_s=now_s로 보낸다.
    @param cmds 특정 틱에만 추가할 운전자 명령 {cs: CMD}
    @return {cs: 출력}
    """
    cmds = cmds or {}
    return {
        k: send(c, k, command=cmds.get(k), **kw) for k in range(first, last + 1)
    }


def _plain(value: object) -> object:
    """!@brief 열거형은 문자열로 바꾼다 (실패 메시지 가독성)."""
    return str(value) if isinstance(value, StrEnum) else value


def _door(side: str, spec: tuple[str, str | None] | None) -> dict[str, object]:
    """!@brief (출력, reason) 기대값을 필드 dict로 바꾼다 (reason None 제외)."""
    if spec is None:
        return {}
    lock, reason = spec
    return {f"lock_{side}": lock, f"reason_{side}": reason}


def check(
    out: Output,
    at: int,
    *,
    both: tuple[str, str | None] | None = None,
    left: tuple[str, str | None] | None = None,
    right: tuple[str, str | None] | None = None,
    pr: str | None = None,
    **extra: object,
) -> None:
    """!
    @brief 한 틱의 출력을 명세 기대값과 비교한다.
    @param out 출력
    @param at 시각 (cs, 메시지용)
    @param both 좌/우 공통 (출력, reason)
    @param left 왼쪽 (출력, reason)
    @param right 오른쪽 (출력, reason)
    @param pr priority_reason (reason_code도 같은 값)
    @param extra st/iv/wc/ovl/ovr. None이면 판정 제외
    """
    want = dict(_DEFAULTS)
    want.update(_door("left", left or both))
    want.update(_door("right", right or both))
    if pr is not None:
        want["priority_reason"] = want["reason_code"] = pr
    want.update({_ALIAS[k]: v for k, v in extra.items()})
    want = {k: v for k, v in want.items() if v is not None}
    got = {k: _plain(getattr(out, k)) for k in want}
    assert got == want, f"now_s={ts(at)}"


def check_range(
    outs: dict[int, Output], first: int, last: int, **exp: object
) -> None:
    """!@brief first~last 모든 틱에 같은 기대값을 적용한다."""
    for k in range(first, last + 1):
        check(outs[k], k, **exp)


# ------------------------------------------------------------ 명령 검증


def test_stc_f_001_invalid_command_values_rejected():
    """!@brief STC-F-001: 목록 밖 명령 값 5종은 그 명령만 거절되고
    출력이 바뀌지 않는다 (SWR-001, SWR-013)."""
    c = ChildLockController()
    check(send(c, 10000), 10000, st="NORMAL")
    bad = [
        cmd("front", "lock", "physical_button"),
        cmd("all", "toggle", "avn"),
        cmd("all", "lock", "bluetooth"),
        cmd("ALL", "lock", "voice"),
        cmd("left", "Lock", "voice"),
    ]
    for k, command in enumerate(bad, start=10001):
        out = send(c, k, command=command)
        check(
            out,
            k,
            both=(REL, "INPUT_INVALID"),
            st="NORMAL",
            pr="INPUT_INVALID",
            iv="INVALID",
        )
    check(send(c, 10006), 10006, both=(REL, "NO_CHANGE"))


def test_stc_f_002_malformed_command_shapes_rejected():
    """!@brief STC-F-002: 필드 누락·null·정수·비객체·빈 객체 명령이
    예외 없이 거절된다 (SWR-001, SWR-013)."""
    c = ChildLockController()
    send(c, 10000)
    bad: list[object] = [
        {"side": "all", "action": "lock"},
        {"side": None, "action": "lock", "source": "avn"},
        {"side": "all", "action": 1, "source": "avn"},
        "lock",
        {},
    ]
    for k, command in enumerate(bad, start=10001):
        out = send(c, k, command=command)
        check(
            out,
            k,
            both=(REL, "INPUT_INVALID"),
            st="NORMAL",
            pr="INPUT_INVALID",
            iv="INVALID",
        )
    check(send(c, 10006), 10006, both=(REL, "NO_CHANGE"))


def test_stc_f_003_bad_command_does_not_block_vehicle_rules():
    """!@brief STC-F-003: 잘못된 명령이 같은 스냅샷의 자동 잠금·화재
    해제를 막지 않는다 (SWR-001, SWR-003, SWR-017, SWR-013)."""
    # Step 1
    c = ChildLockController()
    send(c, 10000)
    out = send(
        c,
        10001,
        vehicle_speed_kph=5.0,
        command=cmd("front", "lock", "avn"),
    )
    check(
        out,
        10001,
        both=(LOCK, "AUTO_LOCK_SPEED"),
        st="NORMAL",
        pr="AUTO_LOCK_SPEED",
        iv="INVALID",
    )
    # Step 2
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    out = send(
        c,
        10001,
        fire_detected=True,
        command=cmd("all", "toggle", "voice"),
    )
    check(
        out,
        10001,
        both=(REL, "FIRE_RELEASE"),
        st="NORMAL",
        pr="FIRE_RELEASE",
        iv="INVALID",
    )


# ------------------------------------------------------------ 차속


def test_stc_f_004_auto_lock_speed_threshold():
    """!@brief STC-F-004: 자동 잠금 3.0 km/h 경계(2.9, 2.999, 3.0)와
    하강 시 LOCK 유지 (SWR-003)."""
    c = ChildLockController()
    send(c, 10000)
    outs = {
        k: send(c, k, vehicle_speed_kph=v)
        for k, v in zip(
            range(10001, 10006), (2.9, 2.999, 3.0, 2.9, 0.0), strict=True
        )
    }
    check(outs[10001], 10001, both=(REL, "NO_CHANGE"), st="NORMAL")
    check(outs[10002], 10002, both=(REL, "NO_CHANGE"))
    check(
        outs[10003], 10003, both=(LOCK, "AUTO_LOCK_SPEED"), pr="AUTO_LOCK_SPEED"
    )
    check(outs[10004], 10004, both=(LOCK, "NO_CHANGE"))
    check(outs[10005], 10005, both=(LOCK, "NO_CHANGE"))


def test_stc_f_005_speed_range_bounds_use_last_valid_value():
    """!@brief STC-F-005: 차속 범위 경계 0.0/300.0 유효, 300.1/-0.1은
    직전 유효값으로 대체 (SWR-003, SWR-013)."""
    # Step 1
    c = ChildLockController()
    out = send(c, 10000, vehicle_speed_kph=300.0)
    check(out, 10000, both=(LOCK, "AUTO_LOCK_SPEED"), iv="VALID")
    # Step 2
    c = ChildLockController()
    send(c, 10000, vehicle_speed_kph=2.9)
    out = send(c, 10001, vehicle_speed_kph=300.1)
    check(out, 10001, both=(REL, "INPUT_INVALID"), iv="INVALID")
    # Step 3
    c = ChildLockController()
    out = send(c, 10000, vehicle_speed_kph=3.5)
    check(out, 10000, both=(LOCK, "AUTO_LOCK_SPEED"))
    out = send(
        c,
        10001,
        vehicle_speed_kph=-0.1,
        command=cmd("all", "unlock", "avn"),
    )
    check(out, 10001, both=(LOCK, "AUTO_LOCK_SPEED"), iv="INVALID")
    # Step 4
    c = ChildLockController()
    out = send(c, 10000, vehicle_speed_kph=0.0)
    check(out, 10000, both=(REL, "NO_CHANGE"), iv="VALID")


def test_stc_f_006_speed_type_errors_use_last_valid_value():
    """!@brief STC-F-006: 차속 형식 오류(bool, 문자열, NaN, inf, 누락)는
    직전 유효값 2.9로 대체 (SWR-003, SWR-013)."""
    c = ChildLockController()
    send(c, 10000, vehicle_speed_kph=2.9)
    cases: list[dict[str, object]] = [
        {"vehicle_speed_kph": True},
        {"vehicle_speed_kph": "5.0"},
        {"vehicle_speed_kph": math.nan},
        {"vehicle_speed_kph": math.inf},
        {"drop": ("vehicle_speed_kph",)},
    ]
    for k, kw in enumerate(cases, start=10001):
        out = send(c, k, **kw)
        check(out, k, both=(REL, "INPUT_INVALID"), st="NORMAL", iv="INVALID")
    out = send(c, 10006, vehicle_speed_kph=2.9)
    check(out, 10006, both=(REL, "NO_CHANGE"), iv="VALID")


def test_stc_f_007_unlock_at_speed_boundary():
    """!@brief STC-F-007: 2.9 km/h에서는 unlock 적용, 3.0 km/h에서는
    AUTO_LOCK_SPEED로 거절 (SWR-002, SWR-003, SWR-004)."""
    c = ChildLockController()
    out = send(
        c, 10000, vehicle_speed_kph=2.9, command=cmd("all", "lock", "avn")
    )
    check(out, 10000, both=(LOCK, "DRIVER_LOCK"))
    out = send(
        c, 10001, vehicle_speed_kph=2.9, command=cmd("all", "unlock", "avn")
    )
    check(out, 10001, both=(REL, "DRIVER_RELEASE"))
    out = send(
        c, 10002, vehicle_speed_kph=2.9, command=cmd("all", "lock", "voice")
    )
    check(out, 10002, both=(LOCK, "DRIVER_LOCK"))
    out = send(
        c, 10003, vehicle_speed_kph=3.0, command=cmd("all", "unlock", "voice")
    )
    check(out, 10003, both=(LOCK, "AUTO_LOCK_SPEED"), pr="AUTO_LOCK_SPEED")
    out = send(c, 10004, vehicle_speed_kph=3.0)
    check(out, 10004, both=(LOCK, "AUTO_LOCK_SPEED"))


# ------------------------------------------------------------ 충돌·오류


def _emergency(out: Output, k: int, iv: str = "INVALID") -> None:
    """!@brief 좌/우 RELEASE/CRASH_CONFIRMED, ST=EMERGENCY 판정."""
    check(
        out,
        k,
        both=(REL, "CRASH_CONFIRMED"),
        st="EMERGENCY",
        pr="CRASH_CONFIRMED",
        iv=iv,
    )


def test_stc_f_008_confirmed_crash_applies_despite_errors():
    """!@brief STC-F-008: CONFIRMED는 다른 오류·순서 무효·갱신 지연과
    함께 와도 적용된다 (SWR-013, SWR-007)."""
    errors: list[dict[str, object]] = [
        {"vehicle_speed_kph": 301},
        {"command": cmd("x", "lock", "avn")},
        {"fire_detected": "yes", "isofix_left": 1, "adult_present": None},
        {"timestamp_s": math.nan},
    ]
    # Step 1, 2, 3, 5
    for kw in errors:
        c = ChildLockController()
        send(c, 10000, command=LOCK_ALL)
        _emergency(send(c, 10001, crash_status="CONFIRMED", **kw), 10001)
    # Step 4: 같은 timestamp 재전송 프레임
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    send(c, 10001, timestamp_s=100.01)
    out = send(c, 10002, timestamp_s=100.01, crash_status="CONFIRMED")
    _emergency(out, 10002)
    # Step 6: 갱신 지연 중
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    outs = hold(c, 10001, 10030, overtemperature_detected="x")
    check_range(
        outs,
        10021,
        10030,
        both=(LOCK, "INPUT_STALE"),
        st="DEGRADED",
        iv="STALE",
    )
    out = send(c, 10031, overtemperature_detected="x", crash_status="CONFIRMED")
    _emergency(out, 10031, iv="STALE")


def test_stc_f_009_crash_status_format_errors_not_confirmed():
    """!@brief STC-F-009: crash_status 목록 밖·형식 오류 6종은 EMERGENCY를
    만들지 않고, 정상 CONFIRMED는 즉시 적용 (SWR-013, SWR-007)."""
    c = ChildLockController()
    send(c, 10000)
    values: list[object] = ["confirmed", "CONFIRMED ", "UNKNOWN", 2, True, None]
    for k, value in enumerate(values, start=10001):
        out = send(c, k, crash_status=value)
        check(out, k, both=(REL, "INPUT_INVALID"), st="NORMAL", iv="INVALID")
    _emergency(send(c, 10007, crash_status="CONFIRMED"), 10007, iv="VALID")


def test_stc_f_010_invalid_crash_status_keeps_pending():
    """!@brief STC-F-010: 오류 crash_status는 직전 유효값 PENDING으로
    대체되어 자동 잠금을 막는다 (SWR-013, SWR-008)."""
    c = ChildLockController()
    out = send(c, 10000, crash_status="PENDING")
    check(out, 10000, both=(REL, None), st="NORMAL")  # reason 판정 제외 TQ-01
    out = send(c, 10001, crash_status="bad", vehicle_speed_kph=5.0)
    check(
        out,
        10001,
        both=(REL, "CRASH_PENDING"),
        st="NORMAL",
        pr="CRASH_PENDING",
        iv="INVALID",
    )
    out = send(c, 10002, crash_status="NONE", vehicle_speed_kph=5.0)
    check(
        out,
        10002,
        both=(LOCK, "AUTO_LOCK_SPEED"),
        pr="AUTO_LOCK_SPEED",
        iv="VALID",
    )


def test_stc_f_011_bool_field_type_errors_not_truthy():
    """!@brief STC-F-011: bool 필드 형식 오류(1, 0, 'false', 누락)가
    truthy로 해석되지 않는다 (SWR-013, 017, 020, 021)."""
    c = ChildLockController()
    out = send(c, 10000, command=LOCK_ALL)
    check(out, 10000, both=(LOCK, "DRIVER_LOCK"), st="NORMAL")
    cases: list[dict[str, object]] = [
        {"fire_detected": 1},
        {"ignition_on": 0},
        {"sensor_fault": "false"},
        {"drop": ("adult_present",)},
    ]
    for k, kw in enumerate(cases, start=10001):
        out = send(c, k, **kw)
        check(
            out,
            k,
            both=(LOCK, "INPUT_INVALID"),
            st="NORMAL",
            wc="NONE",
            iv="INVALID",
        )
    check(send(c, 10005), 10005, both=(LOCK, "NO_CHANGE"), iv="VALID")


def test_stc_f_012_timestamp_errors_make_frame_order_invalid():
    """!@brief STC-F-012: timestamp_s 오류 4종 프레임은 순서 무효라
    차속 5.0이 판정에 쓰이지 않는다 (SWR-013)."""
    c = ChildLockController()
    send(c, 10000)
    cases: list[dict[str, object]] = [
        {"timestamp_s": True},
        {"timestamp_s": "100.02"},
        {"timestamp_s": math.nan},
        {"drop": ("timestamp_s",)},
    ]
    for k, kw in enumerate(cases, start=10001):
        out = send(c, k, vehicle_speed_kph=5.0, **kw)
        check(out, k, both=(REL, "INPUT_INVALID"), st="NORMAL", iv="INVALID")
    out = send(c, 10005, vehicle_speed_kph=5.0)
    check(out, 10005, both=(LOCK, "AUTO_LOCK_SPEED"), iv="VALID")


def test_stc_f_013_stale_frames_do_not_overwrite_new_data():
    """!@brief STC-F-013: 과거·같은 시각 프레임은 새 데이터와 그 안의
    명령을 쓰지 않는다 (SWR-013, SWR-005)."""
    c = ChildLockController()
    send(c, 10000)
    out = send(c, 10001, rear_left_approach_risk=True)
    check(
        out,
        10001,
        left=(LOCK, "APPROACH_RISK_LOCK"),
        right=(REL, "NO_CHANGE"),
        pr="APPROACH_RISK_LOCK",
    )
    for k, stamp in ((10002, 100.00), (10003, 100.01)):
        out = send(c, k, timestamp_s=stamp, rear_left_approach_risk=False)
        check(
            out,
            k,
            left=(LOCK, "APPROACH_RISK_LOCK"),
            right=(REL, "INPUT_INVALID"),
            iv="INVALID",
        )
    out = send(c, 10004, rear_left_approach_risk=False)
    check(out, 10004, left=(LOCK, "NO_CHANGE"), right=(REL, "NO_CHANGE"))
    out = send(
        c, 10005, timestamp_s=100.00, command=cmd("all", "unlock", "voice")
    )
    check(
        out,
        10005,
        left=(LOCK, "INPUT_INVALID"),
        right=(REL, "INPUT_INVALID"),
        iv="INVALID",
    )


# ------------------------------------------------------------ 갱신 지연


def test_stc_f_014_only_order_invalid_frames_go_stale_after_200ms():
    """!@brief STC-F-014: 순서 무효 프레임만 오면 0.200 s 정각은 정상,
    0.210 s에 DEGRADED (SWR-013)."""
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    outs = hold(c, 10001, 10021, timestamp_s=100.00)
    check_range(
        outs,
        10001,
        10020,
        both=(LOCK, "INPUT_INVALID"),
        st="NORMAL",
        iv="INVALID",
    )
    check(
        outs[10021],
        10021,
        both=(LOCK, "INPUT_STALE"),
        st="DEGRADED",
        pr="INPUT_STALE",
        iv="STALE",
    )


_DECISION_FIELDS = (
    "vehicle_speed_kph",
    "crash_status",
    "rear_left_approach_risk",
    "rear_right_approach_risk",
    "fire_detected",
    "overtemperature_detected",
    "adult_present",
    "isofix_left",
    "isofix_right",
    "ignition_on",
    "sensor_fault",
)


def test_stc_f_015_each_decision_field_goes_stale_gear_does_not():
    """!@brief STC-F-015: 판정 필드 11개 각각의 지속 오류는 0.210 s에
    DEGRADED, gear 오류는 DEGRADED가 아님 (SWR-013)."""
    # Step 1~11
    for field in _DECISION_FIELDS:
        c = ChildLockController()
        send(c, 10000)
        outs = hold(c, 10001, 10021, **{field: "x"})
        check_range(outs, 10001, 10020, st="NORMAL", iv="INVALID")
        check(
            outs[10021],
            10021,
            both=(REL, "INPUT_STALE"),
            st="DEGRADED",
            pr="INPUT_STALE",
            iv="STALE",
        )
    # Step 12
    c = ChildLockController()
    send(c, 10000)
    outs = hold(c, 10001, 10060, gear="X")
    check_range(
        outs,
        10001,
        10060,
        both=(REL, "INPUT_INVALID"),
        st="NORMAL",
        iv="INVALID",
    )


def test_stc_f_016_input_loss_degraded_after_exactly_200ms():
    """!@brief STC-F-016: 입력 단절 후 0.200 s 정각은 정상, 0.210 s에
    DEGRADED, 출력 유지 (SWR-013, SWR-010)."""
    c = ChildLockController()
    out = send(c, 10000, command=LOCK_ALL)
    check(out, 10000, both=(LOCK, "DRIVER_LOCK"))
    outs = hold(c, 10001, 10004)
    check_range(outs, 10001, 10004, both=(LOCK, "NO_CHANGE"), st="NORMAL")
    outs = idle(c, 10005, 10024)
    check_range(
        outs, 10005, 10024, both=(LOCK, "NO_CHANGE"), st="NORMAL", iv="VALID"
    )
    stale = {
        "both": (LOCK, "INPUT_STALE"),
        "st": "DEGRADED",
        "pr": "INPUT_STALE",
        "iv": "STALE",
    }
    for k in (10025, 10026, 10030):
        check(c.tick(ts(k), None), k, **stale)


def _degraded_then(step5: bool) -> ChildLockController:
    """!
    @brief STC-F-017 공통 구간: LOCK(Step 5는 없음) 후 입력 단절 0.50 s.
    @param step5 True면 100.00에 BASE만 보낸다
    @return 100.50까지 진행한 제어기
    """
    c = ChildLockController()
    send(c, 10000, command=None if step5 else LOCK_ALL)
    lock = REL if step5 else LOCK
    outs = idle(c, 10001, 10050)
    check_range(outs, 10001, 10020, st="NORMAL", iv="VALID")
    check_range(
        outs,
        10021,
        10050,
        both=(lock, "INPUT_STALE"),
        st="DEGRADED",
        iv="STALE",
    )
    return c


def test_stc_f_017_recovery_tick_reevaluates_rules():
    """!@brief STC-F-017: DEGRADED 복귀 틱에 상태 결정표와 규칙을 다시
    평가한다 (SWR-013, 003, 020, 021)."""
    # Step 1
    c = _degraded_then(step5=False)
    check(
        send(c, 10051), 10051, both=(LOCK, "NO_CHANGE"), st="NORMAL", iv="VALID"
    )
    # Step 2
    c = _degraded_then(step5=False)
    out = send(c, 10051, fire_detected="x")
    check(out, 10051, both=(LOCK, "INPUT_STALE"), st="DEGRADED", iv="STALE")
    check(send(c, 10052), 10052, st="NORMAL", iv="VALID")
    # Step 3
    c = _degraded_then(step5=False)
    out = send(c, 10051, sensor_fault=True)
    check(
        out,
        10051,
        both=(LOCK, "SENSOR_FAULT"),
        st="FAULT",
        wc="SENSOR_FAULT",
        iv="VALID",
    )
    # Step 4
    c = _degraded_then(step5=False)
    out = send(c, 10051, ignition_on=False)
    check(out, 10051, both=(REL, "IGNITION_OFF"), st="OFF", iv="VALID")
    # Step 5
    c = _degraded_then(step5=True)
    out = send(c, 10051, vehicle_speed_kph=5.0)
    check(out, 10051, both=(LOCK, "AUTO_LOCK_SPEED"), st="NORMAL", iv="VALID")


def test_stc_f_018_commands_rejected_while_one_field_stale():
    """!@brief STC-F-018: 한 필드만 갱신 지연인 DEGRADED 중에도 명령과
    자동 잠금을 거절 (SWR-013, 001, 002, 003, 004)."""
    # Step 1
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    outs = hold(c, 10001, 10030, overtemperature_detected="x")
    check_range(outs, 10021, 10030, st="DEGRADED", iv="STALE")
    out = send(
        c,
        10031,
        overtemperature_detected="x",
        command=cmd("all", "unlock", "mobile_app"),
    )
    check(
        out,
        10031,
        both=(LOCK, "INPUT_STALE"),
        st="DEGRADED",
        pr="INPUT_STALE",
        iv="STALE",
    )
    # Step 2
    c = ChildLockController()
    send(c, 10000)
    hold(c, 10001, 10030, overtemperature_detected="x")
    out = send(
        c,
        10031,
        overtemperature_detected="x",
        vehicle_speed_kph=5.0,
        command=cmd("all", "lock", "mobile_app"),
    )
    check(out, 10031, both=(REL, "INPUT_STALE"), st="DEGRADED", iv="STALE")


def test_stc_f_019_gear_is_format_checked_only():
    """!@brief STC-F-019: gear는 형식만 검사하고 판정에 쓰지 않으며,
    gear 오류 지속은 STALE이 아니다 (SWR-013)."""
    c = ChildLockController()
    send(c, 10000)
    for k, gear in zip(range(10001, 10005), "RDNP", strict=True):
        out = send(c, k, gear=gear)
        check(out, k, both=(REL, "NO_CHANGE"), st="NORMAL", iv="VALID")
    outs = hold(c, 10005, 10060, gear="X")
    check_range(
        outs,
        10005,
        10060,
        both=(REL, "INPUT_INVALID"),
        st="NORMAL",
        iv="INVALID",
    )


def test_stc_f_020_staleness_measured_with_now_s_not_timestamp():
    """!@brief STC-F-020: 경과 시간은 timestamp_s가 아니라 now_s로
    잰다 (SWR-013)."""
    for offset in (500.0, -50.0):  # Step 1, Step 2
        c = ChildLockController()
        outs = {
            k: send(
                c,
                k,
                timestamp_s=ts(k) + offset,
                command=LOCK_ALL if k == 10000 else None,
            )
            for k in range(10000, 10005)
        }
        outs |= idle(c, 10005, 10025)
        check_range(outs, 10000, 10024, both=(LOCK, None), st="NORMAL")
        check(
            outs[10025],
            10025,
            both=(LOCK, "INPUT_STALE"),
            st="DEGRADED",
            iv="STALE",
        )


def test_stc_f_021_bogus_future_timestamp_blocks_until_crash():
    """!@brief STC-F-021: 큰 timestamp 한 건 뒤 정상 프레임은 순서 무효,
    DEGRADED가 되어도 CONFIRMED는 적용 (SWR-013, 019, 017)."""
    c = ChildLockController()
    # 명세 절차의 '%s'(서식 누락)는 '(좌/우 LOCK)' 표기에 따라
    # BASE+CMD(all,lock,physical_button)로 해석한다
    send(c, 10000, command=LOCK_ALL)
    out = send(c, 10001, timestamp_s=5000.0)
    check(out, 10001, both=(LOCK, "NO_CHANGE"), iv="VALID")
    outs = hold(c, 10002, 10029)
    outs[10030] = send(c, 10030, fire_detected=True)
    outs |= hold(c, 10031, 10040)
    check_range(
        outs,
        10002,
        10021,
        both=(LOCK, "INPUT_INVALID"),
        st="NORMAL",
        iv="INVALID",
    )
    check_range(
        outs,
        10022,
        10040,
        both=(LOCK, "INPUT_STALE"),
        st="DEGRADED",
        iv="STALE",
    )
    out = send(c, 10041, crash_status="CONFIRMED")
    _emergency(out, 10041, iv="STALE")


def test_stc_f_022_staleness_boundary_near_clock_maximum():
    """!@brief STC-F-022: now_s 상한(≈1e9) 근처에서도 0.200 s 정각은
    정상, 0.210 s는 DEGRADED (SWR-013, SWR-003)."""
    base = 99_999_999_950  # 999999999.50 s
    c = ChildLockController()
    send(c, base, command=LOCK_ALL)
    outs = idle(c, base + 1, base + 21)
    check_range(
        outs,
        base + 1,
        base + 20,
        both=(LOCK, "NO_CHANGE"),
        st="NORMAL",
        iv="VALID",
    )
    check(
        outs[base + 21],
        base + 21,
        both=(LOCK, "INPUT_STALE"),
        st="DEGRADED",
        iv="STALE",
    )


# ------------------------------------------------------------ 접근위험·override

UNLOCK_LEFT = cmd("left", "unlock", "avn")


def test_stc_f_023_approach_risk_left_locks_and_suppresses_unlock():
    """!@brief STC-F-023: 좌 접근위험은 LOCK·해제 억제, 우 unlock은
    우만 해제 (SWR-005, SWR-009)."""
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    out = send(c, 10001, rear_left_approach_risk=True)
    check(
        out,
        10001,
        left=(LOCK, "APPROACH_RISK_LOCK"),
        right=(LOCK, "NO_CHANGE"),
        pr="APPROACH_RISK_LOCK",
    )
    out = send(c, 10002, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    check(
        out,
        10002,
        left=(LOCK, "APPROACH_RISK_LOCK"),
        right=(LOCK, "NO_CHANGE"),
        ovl=False,
    )
    out = send(
        c,
        10003,
        rear_left_approach_risk=True,
        command=cmd("right", "unlock", "avn"),
    )
    check(
        out,
        10003,
        left=(LOCK, "APPROACH_RISK_LOCK"),
        right=(REL, "DRIVER_RELEASE"),
        pr="APPROACH_RISK_LOCK",
    )


def test_stc_f_024_override_window_boundary_10s():
    """!@brief STC-F-024: override 경계 9.99/10.00 s 인정, 10.01 s는 새 첫
    요청으로 억제 시각 갱신 (SWR-006, SWR-005)."""
    c = ChildLockController()
    send(c, 11800, command=LOCK_ALL)
    cmds = {
        11802: UNLOCK_LEFT,
        12801: UNLOCK_LEFT,
        12802: cmd("left", "unlock", "voice"),
        12803: cmd("left", "unlock", "voice"),
        13803: cmd("left", "unlock", "mobile_app"),
    }
    outs = hold(c, 11801, 13804, cmds, rear_left_approach_risk=True)
    # 전 구간: 우 LOCK/NO_CHANGE, OVR=false, ST=NORMAL
    check_range(
        outs, 11801, 13804, right=(LOCK, "NO_CHANGE"), st="NORMAL", ovl=None
    )
    risk = (LOCK, "APPROACH_RISK_LOCK")
    override = (LOCK, "OVERRIDE_REQUESTED")
    check_range(outs, 11801, 12800, left=risk, ovl=False)
    for k in (12801, 12802, 13803):
        check(outs[k], k, left=override, ovl=True)
    check(outs[12803], 12803, left=risk, ovl=False)
    check_range(outs, 12804, 13802, left=risk, ovl=False)
    check(outs[13804], 13804, left=(LOCK, None), ovl=True)  # reason TQ-12


def test_stc_f_025_override_requires_unlock_targeting_same_door():
    """!@brief STC-F-025: 다른 도어 unlock·lock은 억제 시각과 override에
    영향이 없고 side=all은 인정 (SWR-006, SWR-005)."""
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    cmds = {
        10010: cmd("right", "unlock", "voice"),
        10020: cmd("left", "unlock", "voice"),
        10030: cmd("right", "lock", "voice"),
        10040: cmd("right", "unlock", "mobile_app"),
        10050: cmd("all", "unlock", "avn"),
    }
    outs = hold(c, 10001, 10050, cmds, rear_left_approach_risk=True)
    risk = (LOCK, "APPROACH_RISK_LOCK")
    check(outs[10010], 10010, left=risk, right=(REL, "DRIVER_RELEASE"))
    check(outs[10020], 10020, left=risk, right=(REL, "NO_CHANGE"))
    check(outs[10030], 10030, left=risk, right=(LOCK, "DRIVER_LOCK"))
    check(outs[10040], 10040, left=risk, right=(REL, "DRIVER_RELEASE"))
    check(
        outs[10050],
        10050,
        left=(LOCK, "OVERRIDE_REQUESTED"),
        right=(REL, "DRIVER_RELEASE"),
        ovl=True,
        ovr=False,
        pr="OVERRIDE_REQUESTED",
    )


def test_stc_f_026_override_cleared_when_risk_ends():
    """!@brief STC-F-026: 접근위험 FALSE 틱에 override·억제 시각을 지우고,
    재발생 후 첫 unlock은 새 첫 요청 (SWR-006, SWR-005)."""
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    risk = (LOCK, "APPROACH_RISK_LOCK")
    check(send(c, 10001, rear_left_approach_risk=True), 10001, left=risk)
    out = send(c, 10002, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    check(out, 10002, left=risk, ovl=False)
    out = send(c, 10003, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    check(out, 10003, left=(LOCK, "OVERRIDE_REQUESTED"), ovl=True)
    out = send(c, 10004)
    check(out, 10004, left=(LOCK, "NO_CHANGE"), right=(LOCK, "NO_CHANGE"))
    out = send(c, 10005, rear_left_approach_risk=True)
    check(out, 10005, left=risk, ovl=False)
    out = send(c, 10006, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    check(out, 10006, left=risk, ovl=False)
    check(send(c, 10007), 10007, left=(LOCK, "NO_CHANGE"))
    out = send(c, 10008, command=UNLOCK_LEFT)
    check(
        out,
        10008,
        left=(REL, "DRIVER_RELEASE"),
        right=(LOCK, "NO_CHANGE"),
    )


def test_stc_f_027_off_tick_clears_override_window():
    """!@brief STC-F-027: OFF 틱은 override·억제 시각을 비우고 그 틱의
    unlock은 창을 시작하지 않는다 (SWR-006, SWR-020)."""
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    risk = (LOCK, "APPROACH_RISK_LOCK")
    send(c, 10001, rear_left_approach_risk=True)
    out = send(c, 10002, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    check(out, 10002, left=risk, ovl=False)
    out = send(
        c,
        10003,
        rear_left_approach_risk=True,
        ignition_on=False,
        command=UNLOCK_LEFT,
    )
    check(
        out,
        10003,
        left=risk,
        right=(REL, "IGNITION_OFF"),
        st="OFF",
        pr="APPROACH_RISK_LOCK",
    )
    out = send(c, 10004, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    check(out, 10004, left=risk, right=(REL, "NO_CHANGE"), st="NORMAL")
    out = send(c, 10005, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    check(out, 10005, left=(LOCK, "OVERRIDE_REQUESTED"), ovl=True)


def test_stc_f_028_emergency_clears_override_and_latch_release():
    """!@brief STC-F-028: EMERGENCY 틱은 override를 비우고, 래치 해제 틱에
    접근위험 도어를 다시 LOCK (SWR-006, SWR-007)."""
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    risk = (LOCK, "APPROACH_RISK_LOCK")
    send(c, 10001, rear_left_approach_risk=True)
    out = send(c, 10002, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    check(out, 10002, left=risk, ovl=False)
    out = send(
        c,
        10003,
        rear_left_approach_risk=True,
        crash_status="CONFIRMED",
        command=UNLOCK_LEFT,
    )
    check(out, 10003, both=(REL, "CRASH_CONFIRMED"), st="EMERGENCY")
    outs = hold(
        c, 10004, 10104, rear_left_approach_risk=True, ignition_on=False
    )
    check_range(
        outs, 10004, 10103, both=(REL, "CRASH_CONFIRMED"), st="EMERGENCY"
    )
    check(
        outs[10104],
        10104,
        left=risk,
        right=(REL, "IGNITION_OFF"),
        st="OFF",
        pr="APPROACH_RISK_LOCK",
    )
    out = send(c, 10105, rear_left_approach_risk=True)
    check(out, 10105, left=risk, right=(REL, "NO_CHANGE"), st="NORMAL")
    out = send(c, 10106, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    check(out, 10106, left=risk, ovl=False)
    out = send(c, 10107, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    check(out, 10107, left=(LOCK, "OVERRIDE_REQUESTED"), ovl=True)


def test_stc_f_029_priority_reason_tie_prefers_left():
    """!@brief STC-F-029: 두 도어가 모두 3순위면 priority_reason은
    reason_left (SWR-019, SWR-006, SWR-005)."""
    both_risk = {
        "rear_left_approach_risk": True,
        "rear_right_approach_risk": True,
    }
    unlock_all = cmd("all", "unlock", "avn")
    risk = (LOCK, "APPROACH_RISK_LOCK")
    override = (LOCK, "OVERRIDE_REQUESTED")
    # Step 1
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    send(c, 10001, rear_left_approach_risk=True)
    send(c, 10002, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    out = send(c, 10003, rear_left_approach_risk=True, command=UNLOCK_LEFT)
    check(out, 10003, left=override, ovl=True)
    out = send(c, 10004, command=unlock_all, **both_risk)
    check(
        out,
        10004,
        left=override,
        right=risk,
        ovl=True,
        ovr=False,
        pr="OVERRIDE_REQUESTED",
    )
    # Step 2
    unlock_right = cmd("right", "unlock", "avn")
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    send(c, 10001, rear_right_approach_risk=True)
    send(c, 10002, rear_right_approach_risk=True, command=unlock_right)
    out = send(c, 10003, rear_right_approach_risk=True, command=unlock_right)
    check(out, 10003, right=override, ovr=True)
    out = send(c, 10004, command=unlock_all, **both_risk)
    check(
        out,
        10004,
        left=risk,
        right=override,
        ovl=False,
        ovr=True,
        pr="APPROACH_RISK_LOCK",
    )


def _independence_run(**door_input: object) -> list[Output]:
    """!
    @brief STC-F-030/031 실행: 100.01~100.03에 door_input을 더한다.
    @return 100.00~100.03 출력
    """
    c = ChildLockController()
    unlock_all = cmd("all", "unlock", "avn")
    return [
        send(c, 10000, command=LOCK_ALL),
        send(c, 10001, **door_input),
        send(c, 10002, command=unlock_all, **door_input),
        send(c, 10003, command=unlock_all, **door_input),
    ]


def _check_control(ctl: list[Output]) -> None:
    """!@brief 대조 실행(Ctl) 기대값."""
    check(ctl[0], 10000, both=(LOCK, "DRIVER_LOCK"))
    check(ctl[1], 10001, both=(LOCK, "NO_CHANGE"))
    check(ctl[2], 10002, both=(REL, "DRIVER_RELEASE"))
    check(ctl[3], 10003, both=(REL, "DRIVER_RELEASE"))


def _door_fields(outs: list[Output], side: str) -> list[tuple[object, ...]]:
    """!@brief 한 도어의 (lock, override, reason)을 틱별로 뽑는다."""
    return [
        (
            getattr(o, f"lock_{side}"),
            getattr(o, f"override_{side}"),
            getattr(o, f"reason_{side}"),
        )
        for o in outs
    ]


def test_stc_f_030_left_inputs_do_not_affect_right_door():
    """!@brief STC-F-030: left에만 넣은 접근위험·ISOFIX·override가 right
    출력에 번지지 않는다 (SWR-009, 005, 006, 018)."""
    ctl = _independence_run()
    _check_control(ctl)
    run_a = _independence_run(rear_left_approach_risk=True)
    risk = (LOCK, "APPROACH_RISK_LOCK")
    check(run_a[1], 10001, left=risk)
    check(run_a[2], 10002, left=risk, ovl=False)
    check(run_a[3], 10003, left=(LOCK, "OVERRIDE_REQUESTED"), ovl=True)
    run_b = _independence_run(isofix_left=True)
    for k in (1, 2, 3):
        check(run_b[k], 10000 + k, left=(LOCK, "ISOFIX_LOCK"), ovl=False)
    assert _door_fields(run_a, "right") == _door_fields(ctl, "right")
    assert _door_fields(run_b, "right") == _door_fields(ctl, "right")


def test_stc_f_031_right_inputs_do_not_affect_left_door():
    """!@brief STC-F-031: right에만 넣은 접근위험·ISOFIX·override가 left
    출력에 번지지 않는다 (SWR-009, 005, 006, 018)."""
    ctl = _independence_run()
    _check_control(ctl)
    run_a = _independence_run(rear_right_approach_risk=True)
    risk = (LOCK, "APPROACH_RISK_LOCK")
    check(run_a[1], 10001, right=risk)
    check(run_a[2], 10002, right=risk, ovr=False)
    check(run_a[3], 10003, right=(LOCK, "OVERRIDE_REQUESTED"), ovr=True)
    run_b = _independence_run(isofix_right=True)
    for k in (1, 2, 3):
        check(run_b[k], 10000 + k, right=(LOCK, "ISOFIX_LOCK"), ovr=False)
    assert _door_fields(run_a, "left") == _door_fields(ctl, "left")
    assert _door_fields(run_b, "left") == _door_fields(ctl, "left")


def test_stc_f_032_chattering_risk_never_grants_override():
    """!@brief STC-F-032: 접근위험 채터링 중 unlock 반복은 override가
    되지 않고 FALSE 틱에는 해제 (SWR-006, 005, 002)."""
    c = ChildLockController()
    send(c, 10000)
    for k in range(10001, 10021):
        risk = k % 2 == 1
        out = send(c, k, rear_left_approach_risk=risk, command=UNLOCK_LEFT)
        if risk:
            check(
                out,
                k,
                left=(LOCK, "APPROACH_RISK_LOCK"),
                right=(REL, "NO_CHANGE"),
                ovl=False,
            )
        else:
            check(out, k, left=(REL, "DRIVER_RELEASE"), ovl=False)
        assert "OVERRIDE_REQUESTED" not in (out.reason_left, out.reason_right)


# ------------------------------------------------------------ EMERGENCY 래치


def _confirmed_then_base(c: ChildLockController) -> None:
    """!@brief 100.00 LOCK, 100.01 CONFIRMED, 100.02~100.09 BASE."""
    send(c, 10000, command=LOCK_ALL)
    _emergency(send(c, 10001, crash_status="CONFIRMED"), 10001, iv="VALID")
    check_range(
        hold(c, 10002, 10009),
        10002,
        10009,
        both=(REL, "CRASH_CONFIRMED"),
        st="EMERGENCY",
    )


def test_stc_f_033_latch_survives_all_non_release_inputs():
    """!@brief STC-F-033: EMERGENCY 래치는 NONE 복귀·QM 입력·고장·지연·
    시동 ON 유지로 풀리지 않는다 (SWR-007 외)."""
    c = ChildLockController()
    send(c, 10000, command=LOCK_ALL)
    _emergency(send(c, 10001, crash_status="CONFIRMED"), 10001, iv="VALID")
    latched = {"both": (REL, "CRASH_CONFIRMED"), "st": "EMERGENCY"}
    steps: list[dict[str, object]] = [
        {},
        {"command": cmd("all", "lock", "avn")},
        {"vehicle_speed_kph": 50.0},
        {"isofix_left": True, "isofix_right": True},
        {
            "rear_left_approach_risk": True,
            "command": cmd("left", "unlock", "voice"),
        },
    ]
    for k, kw in enumerate(steps, start=10002):
        check(send(c, k, **kw), k, ovl=False, ovr=False, **latched)
    out = send(c, 10007, sensor_fault=True)
    check(out, 10007, wc="SENSOR_FAULT", **latched)
    check(send(c, 10008), 10008, **latched)
    outs = hold(c, 10009, 10030, overtemperature_detected="x")
    check_range(outs, 10029, 10030, iv="STALE", **latched)
    outs = hold(c, 10031, 10500)
    check_range(outs, 10031, 10500, **latched)


def test_stc_f_034_latch_release_after_exactly_1s_ignition_off():
    """!@brief STC-F-034: ignition_on=FALSE 0.99 s는 EMERGENCY, 1.00 s
    정각에 해제되어 OFF (SWR-007)."""
    c = ChildLockController()
    _confirmed_then_base(c)
    outs = hold(c, 10010, 10110, ignition_on=False)
    check_range(
        outs, 10010, 10109, both=(REL, "CRASH_CONFIRMED"), st="EMERGENCY"
    )
    check(
        outs[10110],
        10110,
        both=(REL, "IGNITION_OFF"),
        st="OFF",
        pr="IGNITION_OFF",
    )


def test_stc_f_035_ignition_on_tick_restarts_latch_count():
    """!@brief STC-F-035: 시동 ON 한 틱이 끼면 FALSE 연속 카운트가 0부터
    다시 시작 (SWR-007)."""
    c = ChildLockController()
    _confirmed_then_base(c)
    outs = hold(c, 10010, 10059, ignition_on=False)
    outs[10060] = send(c, 10060)
    outs |= hold(c, 10061, 10161, ignition_on=False)
    latched = {"both": (REL, "CRASH_CONFIRMED"), "st": "EMERGENCY"}
    check_range(outs, 10010, 10160, **latched)
    check(outs[10161], 10161, both=(REL, "IGNITION_OFF"), st="OFF")


def test_stc_f_036_stale_crash_status_restarts_latch_count():
    """!@brief STC-F-036: crash_status가 최신이 아니면 FALSE 연속
    카운트를 0부터 다시 센다 (SWR-007, SWR-013)."""
    c = ChildLockController()
    _confirmed_then_base(c)
    outs = hold(c, 10010, 10049, ignition_on=False)
    outs |= hold(c, 10050, 10080, ignition_on=False, crash_status="x")
    outs |= hold(c, 10081, 10181, ignition_on=False)
    latched = {"both": (REL, "CRASH_CONFIRMED"), "st": "EMERGENCY"}
    check_range(outs, 10010, 10049, st="EMERGENCY")
    check_range(outs, 10050, 10069, st="EMERGENCY", iv="INVALID")
    check_range(outs, 10070, 10080, iv="STALE", **latched)
    check_range(outs, 10081, 10180, st="EMERGENCY", iv="VALID")
    check(outs[10181], 10181, both=(REL, "IGNITION_OFF"), st="OFF")


def test_stc_f_037_reconfirmed_crash_restarts_latch_count():
    """!@brief STC-F-037: 래치 카운트 중 CONFIRMED가 다시 오면 카운트가
    0부터 다시 시작 (SWR-007)."""
    c = ChildLockController()
    _confirmed_then_base(c)
    outs = hold(c, 10010, 10079, ignition_on=False)
    outs[10080] = send(c, 10080, ignition_on=False, crash_status="CONFIRMED")
    outs |= hold(c, 10081, 10181, ignition_on=False)
    latched = {"both": (REL, "CRASH_CONFIRMED"), "st": "EMERGENCY"}
    check_range(outs, 10010, 10180, **latched)
    check(outs[10181], 10181, both=(REL, "IGNITION_OFF"), st="OFF")


# ------------------------------------------------------------ PENDING


def test_stc_f_038_long_pending_keeps_suppressing_qm_locks():
    """!@brief STC-F-038: PENDING 30 s 지속 중 QM LOCK 억제, 해소 틱에
    ISOFIX·자동 잠금 즉시 적용 (SWR-008, 018, 003, 001)."""
    c = ChildLockController()
    send(c, 10000)
    outs = hold(
        c,
        10001,
        13000,
        {10500: cmd("all", "lock", "avn")},
        crash_status="PENDING",
        vehicle_speed_kph=50.0,
        isofix_left=True,
    )
    check_range(
        outs,
        10001,
        13000,
        both=(REL, "CRASH_PENDING"),
        st="NORMAL",
        pr="CRASH_PENDING",
    )
    out = send(c, 13001, vehicle_speed_kph=50.0, isofix_left=True)
    check(
        out,
        13001,
        left=(LOCK, "ISOFIX_LOCK"),
        right=(LOCK, "AUTO_LOCK_SPEED"),
        pr="ISOFIX_LOCK",
    )


def test_stc_f_039_rejected_locks_not_replayed_after_pending():
    """!@brief STC-F-039: PENDING 중 거절된 LOCK 입력이 해소 뒤 되살아나지
    않는다 (SWR-008, SWR-001, SWR-018)."""
    c = ChildLockController()
    send(c, 10000)
    out = send(c, 10001, crash_status="PENDING", command=LOCK_ALL)
    check(out, 10001, both=(REL, "CRASH_PENDING"))
    out = send(
        c, 10002, crash_status="PENDING", isofix_left=True, isofix_right=True
    )
    check(out, 10002, both=(REL, "CRASH_PENDING"))
    out = send(c, 10003, crash_status="PENDING")
    check(out, 10003, both=(REL, None))  # reason 판정 제외 TQ-01
    check(send(c, 10004), 10004, both=(REL, "NO_CHANGE"), st="NORMAL")
    out = send(c, 10005, isofix_left=True)
    check(out, 10005, left=(LOCK, "ISOFIX_LOCK"), right=(REL, "NO_CHANGE"))


def test_stc_f_040_confirmed_overrides_pending_and_latches():
    """!@brief STC-F-040: PENDING→CONFIRMED 전이 시 EMERGENCY, 래치 중
    PENDING·NONE에도 유지 (SWR-008, SWR-007)."""
    c = ChildLockController()
    out = send(c, 10000, vehicle_speed_kph=50.0)
    check(out, 10000, both=(LOCK, "AUTO_LOCK_SPEED"))
    out = send(c, 10001, vehicle_speed_kph=50.0, crash_status="PENDING")
    check(out, 10001, both=(LOCK, "CRASH_PENDING"), st="NORMAL")
    out = send(c, 10002, vehicle_speed_kph=50.0, crash_status="CONFIRMED")
    check(out, 10002, both=(REL, "CRASH_CONFIRMED"), st="EMERGENCY")
    out = send(c, 10003, vehicle_speed_kph=50.0, crash_status="PENDING")
    check(out, 10003, both=(REL, "CRASH_CONFIRMED"), st="EMERGENCY")
    out = send(c, 10004, vehicle_speed_kph=50.0)
    check(out, 10004, both=(REL, "CRASH_CONFIRMED"), st="EMERGENCY")
