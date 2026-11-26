"""!
@brief U6 제어기 단위 테스트 (SWR-010, 013~016, 019~021, DD-01, SWD 9장).
"""

import pytest

from childlock import controller as controller_module
from childlock.controller import ChildLockController
from childlock.model import (
    INITIAL_OUTPUT,
    InputValidity,
    Lock,
    Reason,
    State,
    TickRejectedError,
    WarningCode,
)
from tests.childlock.test_validation import valid_raw


def started(speed: float = 0.0) -> tuple[ChildLockController, float]:
    """!
    @brief 시동 ON 스냅샷 한 건을 넣은 제어기를 만든다.
    @param speed 차속
    @return (제어기, 마지막 now_s)
    """
    c = ChildLockController()
    c.tick(0.0, valid_raw(timestamp_s=0.0, vehicle_speed_kph=speed))
    return c, 0.0


def test_initial_status_and_no_events():
    c = ChildLockController()
    assert c.status() == INITIAL_OUTPUT
    assert c.events() == ()


@pytest.mark.parametrize(
    "bad",
    [float("nan"), float("inf"), True, -1, -0.5, 1e9 + 1, 10**400, "1", None],
)
def test_now_s_precondition_rejects_bad_values(bad):
    # DD-01: 형식, 유한성, 범위 0~1e9
    with pytest.raises(TickRejectedError):
        ChildLockController().tick(bad)


def test_now_s_must_strictly_increase_after_rounding_to_microseconds():
    c = ChildLockController()
    c.tick(1.0000001)
    with pytest.raises(TickRejectedError):
        c.tick(1.0000002)  # 같은 µs로 반올림됨 (CR-04)
    with pytest.raises(TickRejectedError):
        c.tick(0.5)
    c.tick(1.000002)


def test_int_now_s_is_accepted():
    c = ChildLockController()
    assert c.tick(0).state is State.OFF
    assert c.tick(10**9).state is State.DEGRADED


def test_snapshot_tick_records_even_without_change():
    c = ChildLockController()
    c.tick(0.0, valid_raw(timestamp_s=0.0, ignition_on=False))
    assert len(c.events()) == 1


def test_quiet_tick_without_change_is_not_recorded():
    c, _ = started()
    c.tick(0.01)
    assert len(c.events()) == 1


def test_degraded_transition_without_input_is_recorded():
    # SWR-010 조건 2
    c, _ = started()
    out = c.tick(0.21)
    assert out.state is State.DEGRADED
    assert out.input_validity is InputValidity.STALE
    assert len(c.events()) == 2


def test_reason_only_change_without_input_is_not_recorded():
    # CR-03: reason만 바뀐 틱은 기록하지 않는다
    c = ChildLockController()
    cmd = {"side": "left", "action": "lock", "source": "avn"}
    c.tick(
        0.0,
        valid_raw(timestamp_s=0.0, vehicle_speed_kph=0.0, driver_command=cmd),
    )
    assert c.status().reason_left is Reason.DRIVER_LOCK
    out = c.tick(0.01)
    assert out.reason_left is Reason.NO_CHANGE
    assert len(c.events()) == 1


def test_ignition_on_snapshot_makes_normal():
    c, _ = started()
    out = c.status()
    assert out.state is State.NORMAL
    assert out.input_validity is InputValidity.VALID


def test_confirmed_crash_with_invalid_speed_releases():
    # SWR-007·Q-19: 무관한 필드 오류가 충돌 해제를 막지 않는다
    c, _ = started(speed=50.0)
    assert c.status().lock_left is Lock.LOCK
    raw = valid_raw(
        timestamp_s=0.01, vehicle_speed_kph=301, crash_status="CONFIRMED"
    )
    out = c.tick(0.01, raw)
    assert (out.lock_left, out.lock_right) == (Lock.RELEASE, Lock.RELEASE)
    assert out.state is State.EMERGENCY
    assert out.input_validity is InputValidity.INVALID
    assert out.reason_code is Reason.CRASH_CONFIRMED


def test_priority_reason_tie_prefers_left_and_lower_rank_wins():
    c, _ = started()
    cmd = {"side": "right", "action": "lock", "source": "avn"}
    raw = valid_raw(timestamp_s=0.01, vehicle_speed_kph=0.0, driver_command=cmd)
    out = c.tick(0.01, raw)
    # 왼쪽 12순위 NO_CHANGE, 오른쪽 11순위 DRIVER_LOCK → 오른쪽이 우선
    assert out.priority_reason is Reason.DRIVER_LOCK
    assert out.reason_code is Reason.DRIVER_LOCK
    out = c.tick(0.02, valid_raw(timestamp_s=0.02, fire_detected=True))
    # 같은 순위면 왼쪽
    assert out.priority_reason is out.reason_left is Reason.FIRE_RELEASE


def test_warning_code_follows_sensor_fault_even_in_emergency():
    # RV-23
    c, _ = started()
    raw = valid_raw(
        timestamp_s=0.01, crash_status="CONFIRMED", sensor_fault=True
    )
    out = c.tick(0.01, raw)
    assert out.state is State.EMERGENCY
    assert out.warning_code is WarningCode.SENSOR_FAULT


def test_override_flag_is_reported_in_output():
    c, _ = started()
    unlock = {"side": "left", "action": "unlock", "source": "avn"}
    for i, now in enumerate((0.01, 0.02), start=1):
        raw = valid_raw(
            timestamp_s=float(i),
            rear_left_approach_risk=True,
            driver_command=unlock,
        )
        out = c.tick(now, raw)
    assert out.override_left is True
    assert out.lock_left is Lock.LOCK
    assert out.reason_left is Reason.OVERRIDE_REQUESTED


def test_failed_tick_leaves_state_untouched(monkeypatch):
    # AP-03: 계산 중 예외가 나면 반영하지 않는다
    c, _ = started()
    before = (c.status(), c.events())

    def boom(_inp: object) -> None:
        raise RuntimeError("injected")

    monkeypatch.setattr(controller_module, "arbitrate", boom)
    with pytest.raises(RuntimeError):
        c.tick(0.01, valid_raw(timestamp_s=1.0, fire_detected=True))
    assert (c.status(), c.events()) == before
    monkeypatch.undo()
    # now_s도 반영되지 않았으므로 같은 시각으로 다시 진행할 수 있다
    assert c.tick(0.01).state is State.NORMAL


def test_same_vector_gives_same_outputs_on_new_instances():
    # SWR-016 (단위 수준)
    def run() -> list[object]:
        c = ChildLockController()
        outs = []
        for i in range(50):
            raw = valid_raw(
                timestamp_s=float(i),
                vehicle_speed_kph=float(i % 7),
                rear_left_approach_risk=i % 5 == 0,
            )
            outs.append(c.tick(i * 0.01, raw if i % 3 else None))
        return outs

    assert run() == run()
