"""!
@brief U2 신호 추적 단위 테스트 (SWR-007, SWR-013, SWD-ECL-001 5장).
"""

from childlock.model import DECISION_FIELDS, CrashStatus
from childlock.signals import advance_signals, initial_tracker
from childlock.validation import validate_snapshot
from tests.childlock.test_validation import valid_raw


def us(seconds: float) -> int:
    """!
    @brief 초를 정수 µs로 바꾼다 (제어기와 같은 규칙).
    @param seconds 초
    @return µs
    """
    return round(seconds * 1_000_000)


def test_initial_tracker_starts_with_defaults_and_all_fields_fresh():
    state = initial_tracker(us(5.0))
    _, view = advance_signals(state, validate_snapshot(None), us(5.0))
    assert view.values.ignition_on is False
    assert view.stale is False
    assert view.fresh == frozenset(DECISION_FIELDS)


def test_order_valid_snapshot_updates_values():
    state = initial_tracker(0)
    _, view = advance_signals(state, validate_snapshot(valid_raw()), us(0.01))
    assert view.order_valid is True
    assert view.values.ignition_on is True
    assert view.values.speed_kph == 10.0


def test_exactly_200ms_is_fresh_and_201us_more_is_stale():
    # SWR-013: 정확히 0.200 s는 정상, 초과하면 STALE
    state, _ = advance_signals(
        initial_tracker(0), validate_snapshot(valid_raw()), 0
    )
    _, view = advance_signals(state, validate_snapshot(None), 200_000)
    assert view.stale is False
    _, view = advance_signals(state, validate_snapshot(None), 200_001)
    assert view.stale is True


def test_float_error_pair_does_not_make_exact_200ms_stale():
    # DR-01 회귀: float로는 0.9 - 0.7 = 0.20000000000000007
    # 이지만 µs 정수로는 정확히 200 ms
    state, _ = advance_signals(
        initial_tracker(us(0.7)), validate_snapshot(valid_raw()), us(0.7)
    )
    _, view = advance_signals(state, validate_snapshot(None), us(0.9))
    assert view.stale is False


def test_never_updated_tracker_goes_stale_after_200ms_from_start():
    state = initial_tracker(0)
    _, view = advance_signals(state, validate_snapshot(None), 200_001)
    assert view.stale is True


def test_same_or_older_timestamp_is_order_invalid_and_ignored():
    state, _ = advance_signals(
        initial_tracker(0),
        validate_snapshot(
            valid_raw(timestamp_s=2.0, rear_left_approach_risk=True)
        ),
        us(0.01),
    )
    for ts in (2.0, 1.5):
        stale_frame = valid_raw(timestamp_s=ts, rear_left_approach_risk=False)
        new_state, view = advance_signals(
            state, validate_snapshot(stale_frame), us(0.02)
        )
        assert view.order_valid is False
        assert view.any_invalid is True
        # 옛 프레임의 FALSE가 새 데이터(TRUE)를 덮어쓰지 않는다 (RV-22)
        assert view.values.approach_left is True
        assert new_state.field_time_us == state.field_time_us


def test_order_invalid_frame_drops_command_but_reports_confirmed():
    state, _ = advance_signals(
        initial_tracker(0),
        validate_snapshot(valid_raw(timestamp_s=2.0)),
        us(0.01),
    )
    cmd = {"side": "left", "action": "lock", "source": "avn"}
    old = valid_raw(
        timestamp_s=1.0, crash_status="CONFIRMED", driver_command=cmd
    )
    _, view = advance_signals(state, validate_snapshot(old), us(0.02))
    assert view.command is None
    # Q-21: 유효한 CONFIRMED는 순서와 무관하게 잡는다 (값에는 반영하지 않음)
    assert view.frame_confirmed is True
    assert view.values.crash is CrashStatus.NONE


def test_invalid_timestamp_is_order_invalid():
    _, view = advance_signals(
        initial_tracker(0),
        validate_snapshot(valid_raw(timestamp_s="x")),
        us(0.01),
    )
    assert view.order_valid is False
    assert view.values.ignition_on is False


def test_persistently_invalid_field_makes_view_stale():
    # RV-21: 특정 필드만 계속 오류이면 그 필드 때문에 200 ms 뒤 STALE
    state = initial_tracker(0)
    t = 0
    view = None
    for i in range(1, 25):
        t = us(i * 0.01)
        raw = valid_raw(timestamp_s=float(i), sensor_fault="broken")
        state, view = advance_signals(state, validate_snapshot(raw), t)
    assert view is not None
    assert view.any_invalid is True
    assert view.stale is True
    assert "sensor_fault" not in view.fresh
    assert "ignition_on" in view.fresh


def test_valid_command_passes_through_on_order_valid_frame():
    cmd = {"side": "right", "action": "unlock", "source": "avn"}
    _, view = advance_signals(
        initial_tracker(0),
        validate_snapshot(valid_raw(driver_command=cmd)),
        us(0.01),
    )
    assert view.command is not None
    assert view.any_invalid is False


def test_absent_snapshot_is_not_invalid():
    _, view = advance_signals(initial_tracker(0), validate_snapshot(None), 10)
    assert view.order_valid is False
    assert view.any_invalid is False
    assert view.frame_confirmed is False
