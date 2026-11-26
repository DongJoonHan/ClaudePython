"""!
@brief U1 입력 검증 단위 테스트 (SWR-013, SWD-ECL-001 4장).
"""

import pytest

from childlock.model import Action, CrashStatus, Gear, Side, Source
from childlock.validation import validate_snapshot


def valid_raw(**overrides: object) -> dict[str, object]:
    """!
    @brief 모든 필드가 유효한 원시 스냅샷을 만든다.
    @param overrides 바꿀 필드
    @return 원시 스냅샷 dict
    """
    raw: dict[str, object] = {
        "timestamp_s": 1.0,
        "vehicle_speed_kph": 10.0,
        "gear": "D",
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
    raw.update(overrides)
    return raw


def test_none_means_no_snapshot():
    p = validate_snapshot(None)
    assert p.present is False
    assert p.invalid_fields == frozenset()
    assert p.command is None


def test_valid_snapshot_parses_every_field():
    p = validate_snapshot(valid_raw())
    assert p.present is True
    assert p.timestamp == 1.0
    assert p.invalid_fields == frozenset()
    assert p.update.speed_kph == 10.0
    assert p.update.gear is Gear.D
    assert p.update.crash is CrashStatus.NONE
    assert p.update.ignition_on is True
    assert p.update.approach_left is False


def test_non_dict_snapshot_marks_every_field_invalid():
    p = validate_snapshot([1, 2])
    assert p.present is True
    assert p.timestamp is None
    assert "timestamp_s" in p.invalid_fields
    assert "crash_status" in p.invalid_fields
    assert len(p.invalid_fields) == 13


@pytest.mark.parametrize("speed", [0.0, 300.0, 0, 300, 3.0])
def test_speed_accepts_range_boundaries(speed: object):
    p = validate_snapshot(valid_raw(vehicle_speed_kph=speed))
    assert "vehicle_speed_kph" not in p.invalid_fields
    assert p.update.speed_kph == speed


@pytest.mark.parametrize(
    "speed",
    [-0.1, 300.1, float("nan"), float("inf"), 10**400, True, "1", None],
)
def test_speed_rejects_out_of_range_and_wrong_types(speed: object):
    # 10**400: math.isfinite에서 OverflowError가 나지 않아야 한다 (DR-02)
    p = validate_snapshot(valid_raw(vehicle_speed_kph=speed))
    assert "vehicle_speed_kph" in p.invalid_fields
    assert p.update.speed_kph is None


def test_missing_field_is_invalid():
    raw = valid_raw()
    del raw["sensor_fault"]
    p = validate_snapshot(raw)
    assert p.invalid_fields == frozenset({"sensor_fault"})


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_bool_field_requires_real_bool(value: object):
    p = validate_snapshot(valid_raw(ignition_on=value))
    assert "ignition_on" in p.invalid_fields


@pytest.mark.parametrize("value", ["X", 1, None, "confirmed"])
def test_enum_field_rejects_values_outside_list(value: object):
    p = validate_snapshot(valid_raw(crash_status=value))
    assert "crash_status" in p.invalid_fields


@pytest.mark.parametrize("ts", [None, "1", True, float("nan"), float("-inf")])
def test_timestamp_invalid_values(ts: object):
    p = validate_snapshot(valid_raw(timestamp_s=ts))
    assert p.timestamp is None
    assert "timestamp_s" in p.invalid_fields


def test_huge_int_timestamp_is_valid():
    p = validate_snapshot(valid_raw(timestamp_s=10**400))
    assert p.timestamp == 10**400


def test_valid_command_is_parsed():
    cmd = {"side": "all", "action": "unlock", "source": "voice"}
    p = validate_snapshot(valid_raw(driver_command=cmd))
    assert p.command is not None
    assert p.command.side is Side.ALL
    assert p.command.action is Action.UNLOCK
    assert p.command.source is Source.VOICE
    assert p.command_invalid is False


def test_null_command_means_no_command():
    p = validate_snapshot(valid_raw(driver_command=None))
    assert p.command is None
    assert p.command_invalid is False


@pytest.mark.parametrize(
    "cmd",
    [
        "lock",
        {"action": "lock", "source": "avn"},
        {"side": "left", "source": "avn"},
        {"side": "left", "action": "lock"},
        {"side": "middle", "action": "lock", "source": "avn"},
        {"side": "left", "action": "open", "source": "avn"},
        {"side": "left", "action": "lock", "source": "app"},
    ],
)
def test_invalid_command_is_rejected_alone(cmd: object):
    # 3.2절: 명령 오류는 그 명령만 거절하고 차량 필드에는 영향이 없다
    p = validate_snapshot(valid_raw(driver_command=cmd))
    assert p.command is None
    assert p.command_invalid is True
    assert p.invalid_fields == frozenset()
