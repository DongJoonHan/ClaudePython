"""!
@brief SWE.5 통합 시험: Use Case 시나리오로 C1~C6 연결을 검증한다.

시험 ID(IT-xx)는 통합 시험 명세(ITR-ECL-001)와 같다.
"""

import pytest

from childlock.model import (
    InputValidity,
    Lock,
    Output,
    Reason,
    State,
    WarningCode,
)
from tests.integration.harness import Drive

L, R = Lock.LOCK, Lock.RELEASE


def locks(out: Output) -> tuple[Lock, Lock]:
    """!@brief (좌, 우) 출력."""
    return out.lock_left, out.lock_right


@pytest.mark.parametrize(
    "source", ["physical_button", "avn", "voice", "mobile_app"]
)
def test_it01_driver_commands_per_side(source):
    # UC-01, SWR-001·002·009: 경로마다 좌/우/전체 잠금·해제
    d = Drive()
    assert locks(d.step(("all", "lock"), source)) == (L, L)
    assert locks(d.step(("left", "unlock"), source)) == (R, L)
    assert locks(d.step(("right", "unlock"), source)) == (R, R)
    assert locks(d.step(("right", "lock"), source)) == (R, L)
    out = d.step()
    assert locks(out) == (R, L)
    assert out.reason_code is Reason.NO_CHANGE


def test_it02_drive_away_auto_lock_and_stop_unlock():
    # UC-02, SWR-003·004: 2.9 km/h는 유지, 3.0 km/h부터 잠금, 정지 후 해제 가능
    d = Drive()
    assert locks(d.step(vehicle_speed_kph=2.9)) == (R, R)
    out = d.step(vehicle_speed_kph=3.0)
    assert locks(out) == (L, L)
    assert out.reason_code is Reason.AUTO_LOCK_SPEED
    out = d.step(("all", "unlock"), vehicle_speed_kph=50.0)
    assert locks(out) == (L, L)  # 주행 중 해제는 자동 잠금이 막는다
    d.step(vehicle_speed_kph=0.0)
    assert locks(d.step(("all", "unlock"))) == (R, R)


def test_it03_exit_with_approach_risk_and_override():
    # UC-03, SWR-005·006, Q-01·Q-20
    d = Drive()
    out = d.step(("left", "unlock"), rear_left_approach_risk=True)
    assert locks(out) == (L, R)
    assert out.reason_left is Reason.APPROACH_RISK_LOCK
    d.run(300)  # 3 s 경과, 위험 유지
    out = d.step(("left", "unlock"))
    assert out.override_left is True
    assert out.lock_left is L  # override여도 위험 동안 LOCK
    out = d.step(rear_left_approach_risk=False)
    assert out.override_left is False
    assert out.lock_left is L
    assert locks(d.step(("left", "unlock"))) == (R, R)


def test_it03b_override_window_expires_after_10s():
    d = Drive(rear_left_approach_risk=True)
    d.step(("left", "unlock"))
    d.run(1000)  # 정확히 10.0 s 후
    assert d.step(("left", "unlock")).override_left is False  # 10.01 s
    d.run(100)
    assert d.step(("left", "unlock")).override_left is True  # 새 주기 1.01 s


def test_it04_crash_while_driving_releases_and_latches():
    # UC-04, SWR-007, Q-06, Q-19
    d = Drive()
    assert locks(d.run(10, vehicle_speed_kph=60.0)) == (L, L)
    out = d.step(crash_status="CONFIRMED", vehicle_speed_kph=999)
    assert locks(out) == (R, R)
    assert out.state is State.EMERGENCY
    assert out.input_validity is InputValidity.INVALID
    out = d.step(("all", "lock"), crash_status="NONE", vehicle_speed_kph=60.0)
    assert locks(out) == (R, R)  # 래치 유지
    assert out.state is State.EMERGENCY
    # 시동 OFF를 처음 관측한 틱이 경과 0 s. 100번째 틱이 0.99 s
    out = d.run(100, ignition_on=False)
    assert out.state is State.EMERGENCY
    out = d.step()  # 1.00 s
    assert out.state is State.OFF
    assert locks(out) == (R, R)


def test_it05_pending_then_confirmed():
    # SWR-008: PENDING 중 QM LOCK 미적용, 이후 CONFIRMED 해제
    d = Drive()
    out = d.step(crash_status="PENDING", vehicle_speed_kph=30.0)
    assert locks(out) == (R, R)
    assert out.reason_code is Reason.CRASH_PENDING
    out = d.step(("left", "unlock"), rear_left_approach_risk=True)
    assert out.lock_left is L  # 접근위험(ASIL B)은 PENDING 중에도 적용
    out = d.step(crash_status="CONFIRMED")
    assert locks(out) == (R, R)
    assert out.state is State.EMERGENCY


def test_it06_fire_and_adult_vs_isofix():
    # UC-05·UC-06, SWR-017·018, Q-03·Q-04
    d = Drive()
    assert locks(d.step(isofix_left=True, vehicle_speed_kph=40.0)) == (L, L)
    out = d.step(fire_detected=True)
    assert locks(out) == (R, R)
    assert out.reason_code is Reason.FIRE_RELEASE
    out = d.step(fire_detected=False, vehicle_speed_kph=0.0, adult_present=True)
    assert locks(out) == (L, R)  # ISOFIX 도어는 성인 탑승으로 해제하지 않음
    assert out.reason_right is Reason.ADULT_PRESENT_RELEASE


def test_it07_ignition_off_releases_except_approach_door():
    # UC-07, SWR-020, Q-16
    d = Drive()
    d.step(("all", "lock"))
    out = d.step(ignition_on=False, rear_right_approach_risk=True)
    assert out.state is State.OFF
    assert locks(out) == (R, L)


def test_it08_signal_loss_degraded_and_recovery():
    # UC-08, SWR-013: 200 ms 초과 후 100 ms 안에 DEGRADED, 복귀
    d = Drive()
    d.step(("all", "lock"))
    assert d.idle(20).state is State.NORMAL  # 200 ms
    out = d.idle(1)  # 210 ms
    assert out.state is State.DEGRADED
    assert out.input_validity is InputValidity.STALE
    assert locks(out) == (L, L)
    assert d.step(("all", "unlock")).state is State.NORMAL


def test_it08b_frozen_timestamp_goes_degraded():
    # SWR-013, Q-11: 같은 timestamp 반복(고착 소스)은 갱신이 아니다
    d = Drive()
    d.step(timestamp_s=5.0)
    for _ in range(20):
        out = d.step(timestamp_s=5.0)
    assert out.state is State.NORMAL  # 200 ms까지는 정상
    out = d.step(timestamp_s=5.0)
    assert out.state is State.DEGRADED
    assert out.input_validity is InputValidity.STALE


def test_it08c_reordered_frame_does_not_overwrite_newer_data():
    # RV-22, Q-21: 옛 프레임의 접근위험 FALSE가 새 TRUE를 덮어쓰지 않는다
    d = Drive()
    d.step(rear_left_approach_risk=True)
    out = d.step(
        ("left", "unlock"),
        timestamp_s=0.0,
        rear_left_approach_risk=False,
    )
    assert out.input_validity is InputValidity.INVALID
    assert out.lock_left is L
    assert out.reason_left is Reason.APPROACH_RISK_LOCK


def test_it08d_sensor_fault_holds_and_warns():
    # SWR-021, Q-17
    d = Drive()
    d.run(5, vehicle_speed_kph=40.0)
    out = d.step(sensor_fault=True, vehicle_speed_kph=0.0, fire_detected=True)
    assert out.state is State.FAULT
    assert out.warning_code is WarningCode.SENSOR_FAULT
    assert locks(out) == (L, L)  # Q-18: 고장 중 화재여도 유지 (잔여 위험)
    out = d.step(sensor_fault=False)
    assert out.warning_code is WarningCode.NONE
    assert locks(out) == (R, R)


def test_it09_records_follow_ticks():
    # UC-09, SWR-010·012: 입력 101건 후 최근 100건
    d = Drive()
    d.run(101)
    ids = [r.event_id for r in d.controller.events()]
    assert ids == list(range(2, 102))
    assert d.controller.status() == d.controller.tick(d.now_s + 0.01)


def test_it10_every_reason_code_comes_from_swrs_list():
    # 인터페이스 일관성: 출력 이유 코드는 SWRS 3.4 목록 안에 있다
    d = Drive()
    outs = [
        d.step(("all", "lock")),
        d.step(vehicle_speed_kph=10.0),
        d.step(crash_status="PENDING"),
        d.step(crash_status="CONFIRMED"),
    ]
    for out in outs:
        for reason in (out.reason_left, out.reason_right, out.priority_reason):
            assert reason in set(Reason)
