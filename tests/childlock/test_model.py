"""!
@brief U0 공통 모델 단위 테스트 (SWD-ECL-001 3장).
"""

from childlock.model import (
    DECISION_FIELDS,
    FIELD_MAP,
    INITIAL_OUTPUT,
    DecisionRecord,
    InputValidity,
    Lock,
    Reason,
    Signals,
    State,
    WarningCode,
)


def test_decision_fields_are_signal_fields_except_gear():
    # SWR-013: 판정 필드는 gear를 뺀 11개
    assert len(DECISION_FIELDS) == 11
    assert "gear" not in DECISION_FIELDS
    assert set(DECISION_FIELDS) | {"gear"} == set(FIELD_MAP.values())


def test_signals_defaults_match_swrs_initial_valid_values():
    # SWRS 3.1 초기 유효값
    s = Signals()
    assert s.speed_kph == 0.0
    assert s.gear == "P"
    assert s.crash == "NONE"
    assert s.ignition_on is False
    assert s.sensor_fault is False


def test_initial_output_is_release_off_with_ignition_off_reason():
    # SWR-020: 시작 시 RELEASE/OFF, reason IGNITION_OFF
    assert INITIAL_OUTPUT.lock_left is Lock.RELEASE
    assert INITIAL_OUTPUT.lock_right is Lock.RELEASE
    assert INITIAL_OUTPUT.state is State.OFF
    assert INITIAL_OUTPUT.reason_code is Reason.IGNITION_OFF
    assert INITIAL_OUTPUT.priority_reason is Reason.IGNITION_OFF
    assert INITIAL_OUTPUT.input_validity is InputValidity.VALID
    assert INITIAL_OUTPUT.warning_code is WarningCode.NONE


def test_output_to_dict_uses_swrs_field_names_and_string_values():
    d = INITIAL_OUTPUT.to_dict()
    assert d == {
        "lock_left": "RELEASE",
        "lock_right": "RELEASE",
        "state": "OFF",
        "override_left": False,
        "override_right": False,
        "input_validity": "VALID",
        "reason_left": "IGNITION_OFF",
        "reason_right": "IGNITION_OFF",
        "priority_reason": "IGNITION_OFF",
        "reason_code": "IGNITION_OFF",
        "warning_code": "NONE",
    }


def test_decision_record_has_exactly_swr011_fields():
    # SWR-011: 허용 필드 집합과 정확히 같아야 한다 (reason_code 제외)
    rec = DecisionRecord.from_output(7, 1.5, INITIAL_OUTPUT)
    assert set(rec.to_dict()) == {
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
    assert rec.to_dict()["event_id"] == 7
    assert rec.to_dict()["now_s"] == 1.5


def test_plain_rejects_unserializable_values():
    # 직렬화할 수 없는 값은 조용히 넘기지 않고 예외를 낸다 (DD-04에서 500)
    import pytest

    from childlock.model import _plain

    with pytest.raises(TypeError):
        _plain(object())
