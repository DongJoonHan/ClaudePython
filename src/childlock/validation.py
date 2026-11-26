"""!
@brief C1 입력 검증기: 원시 입력을 필드별로 검사한다 (SWR-013).

SWD-ECL-001 4장. 오류(누락, 형식, 범위, 목록 밖, NaN·무한대)는 필드 단위로
판정하고, 오류 필드는 None으로 표시한다. 명령 오류는 그 명령만 거절한다.
"""

import math
from collections.abc import Mapping
from enum import StrEnum

from childlock.model import (
    FIELD_MAP,
    SPEED_MAX_KPH,
    SPEED_MIN_KPH,
    Action,
    CrashStatus,
    DriverCommand,
    Gear,
    ParsedInput,
    Side,
    SignalUpdate,
    Source,
)

## 오류로 판정할 수 있는 모든 입력 키 (timestamp_s 포함)
_ALL_KEYS = frozenset({"timestamp_s", *FIELD_MAP})


def validate_snapshot(raw: object) -> ParsedInput:
    """!
    @brief 원시 스냅샷을 필드별로 검증한다.
    @param raw None(입력 없음) 또는 dict
    @return 검증 결과
    """
    if raw is None:
        return ParsedInput(present=False)
    if not isinstance(raw, dict):
        # dict가 아니면 어떤 필드도 읽을 수 없다
        return ParsedInput(present=True, invalid_fields=_ALL_KEYS)
    timestamp = _number(raw.get("timestamp_s"))
    update, invalid = _parse_fields(raw)
    if timestamp is None:
        invalid = invalid | {"timestamp_s"}
    command, command_invalid = _parse_command(raw.get("driver_command"))
    return ParsedInput(
        present=True,
        timestamp=timestamp,
        update=update,
        invalid_fields=invalid,
        command=command,
        command_invalid=command_invalid,
    )


def _parse_fields(
    raw: Mapping[str, object],
) -> tuple[SignalUpdate, frozenset[str]]:
    """!
    @brief 차량 필드를 규칙에 따라 변환한다.
    @param raw 원시 스냅샷
    @return (필드별 유효값, 오류 입력 키 집합)
    """
    get = raw.get
    update = SignalUpdate(
        speed_kph=_speed(get("vehicle_speed_kph")),
        gear=_enum_value(get("gear"), Gear),
        crash=_enum_value(get("crash_status"), CrashStatus),
        approach_left=_strict_bool(get("rear_left_approach_risk")),
        approach_right=_strict_bool(get("rear_right_approach_risk")),
        fire=_strict_bool(get("fire_detected")),
        overtemp=_strict_bool(get("overtemperature_detected")),
        adult=_strict_bool(get("adult_present")),
        isofix_left=_strict_bool(get("isofix_left")),
        isofix_right=_strict_bool(get("isofix_right")),
        ignition_on=_strict_bool(get("ignition_on")),
        sensor_fault=_strict_bool(get("sensor_fault")),
    )
    invalid = frozenset(
        key for key, attr in FIELD_MAP.items() if getattr(update, attr) is None
    )
    return update, invalid


def _parse_command(raw: object) -> tuple[DriverCommand | None, bool]:
    """!
    @brief 운전자 명령을 검증한다 (SWRS 3.2).
    @param raw 원시 명령 (None이면 명령 없음)
    @return (유효한 명령 또는 None, 명령 오류 여부)
    """
    if raw is None:
        return None, False
    if not isinstance(raw, dict):
        return None, True
    side = _enum_value(raw.get("side"), Side)
    action = _enum_value(raw.get("action"), Action)
    source = _enum_value(raw.get("source"), Source)
    if side is None or action is None or source is None:
        return None, True
    return DriverCommand(side=side, action=action, source=source), False


def _number(value: object) -> float | None:
    """!
    @brief 유한한 수인지 검사한다. int에는 isfinite를 쓰지 않는다 (DR-02).
    @param value 원시 값
    @return 유효하면 원래 수, 아니면 None
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _speed(value: object) -> float | None:
    """!
    @brief 차속을 검사한다 (0.0~300.0 km/h).
    @param value 원시 값
    @return 유효하면 float 차속, 아니면 None
    """
    number = _number(value)
    if number is None or not SPEED_MIN_KPH <= number <= SPEED_MAX_KPH:
        return None
    return float(number)


def _strict_bool(value: object) -> bool | None:
    """!
    @brief Python bool만 허용한다 (0, 1, 문자열은 형식 오류).
    @param value 원시 값
    @return 유효하면 bool, 아니면 None
    """
    return value if isinstance(value, bool) else None


def _enum_value[E: StrEnum](value: object, enum_cls: type[E]) -> E | None:
    """!
    @brief 문자열이고 열거형 값 목록에 있는지 검사한다.
    @param value 원시 값
    @param enum_cls 대상 열거형
    @return 유효하면 열거형 멤버, 아니면 None
    """
    if not isinstance(value, str):
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return None
