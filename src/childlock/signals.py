"""!
@brief C2 신호 추적기: 필드별 직전 유효값, 갱신 시각, 스냅샷 순서 관리.

SWD-ECL-001 5장 (SWR-007, SWR-013). 순수 함수로 새 상태를 만들고,
반영은 제어기(C6)가 한다(AP-03). 시각은 정수 µs로 비교한다(AD-05).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from childlock.model import (
    DECISION_FIELDS,
    STALE_LIMIT_US,
    CrashStatus,
    ParsedInput,
    Signals,
    SignalUpdate,
    SignalView,
)


@dataclass(frozen=True)
class TrackerState:
    """!@brief 신호 추적기 내부 상태 (C6이 보관)."""

    values: Signals
    field_time_us: Mapping[str, int]
    last_timestamp: float | None


def initial_tracker(now_us: int) -> TrackerState:
    """!
    @brief 첫 틱 시각으로 추적기를 초기화한다 (모든 필드 갱신 시각 = now_us).
    @param now_us 첫 틱 시각 (µs)
    @return 초기 상태
    """
    times = MappingProxyType(dict.fromkeys(DECISION_FIELDS, now_us))
    return TrackerState(
        values=Signals(), field_time_us=times, last_timestamp=None
    )


def advance_signals(
    state: TrackerState, parsed: ParsedInput, now_us: int
) -> tuple[TrackerState, SignalView]:
    """!
    @brief 한 틱의 입력을 반영한 새 상태와 판정용 보기를 만든다.
    @param state 직전 추적기 상태
    @param parsed C1 검증 결과
    @param now_us 현재 틱 시각 (µs)
    @return (새 상태, 신호 보기)
    """
    order_valid = _is_order_valid(state.last_timestamp, parsed)
    if order_valid:
        state = _apply_update(state, parsed, now_us)
    fresh = frozenset(
        name
        for name in DECISION_FIELDS
        if now_us - state.field_time_us[name] <= STALE_LIMIT_US
    )
    view = SignalView(
        values=state.values,
        stale=len(fresh) != len(DECISION_FIELDS),
        fresh=fresh,
        order_valid=order_valid,
        # Q-21: 유효한 CONFIRMED는 순서와 무관하게 래치 판정에 쓴다
        frame_confirmed=parsed.update.crash is CrashStatus.CONFIRMED,
        any_invalid=bool(parsed.invalid_fields)
        or parsed.command_invalid
        or (parsed.present and not order_valid),
        command=parsed.command if order_valid else None,
    )
    return state, view


def _is_order_valid(last: float | None, parsed: ParsedInput) -> bool:
    """!
    @brief 스냅샷 timestamp가 유효하고 엄격히 증가하는지 판정한다.
    @param last 직전 순서 유효 스냅샷의 timestamp
    @param parsed C1 검증 결과
    @return 순서 유효 여부
    """
    if not parsed.present or parsed.timestamp is None:
        return False
    return last is None or parsed.timestamp > last


def _apply_update(
    state: TrackerState, parsed: ParsedInput, now_us: int
) -> TrackerState:
    """!
    @brief 유효 필드로 값과 필드 갱신 시각을 바꾼다.
    @param state 직전 상태
    @param parsed 순서 유효 스냅샷의 검증 결과
    @param now_us 현재 틱 시각 (µs)
    @return 새 상태
    """
    times = dict(state.field_time_us)
    for name in DECISION_FIELDS:
        if getattr(parsed.update, name) is not None:
            times[name] = now_us
    return TrackerState(
        values=_merge_values(parsed.update, state.values),
        field_time_us=MappingProxyType(times),
        last_timestamp=parsed.timestamp,
    )


def _merge_values(update: SignalUpdate, old: Signals) -> Signals:
    """!
    @brief 유효한 새 값은 쓰고, 오류 필드(None)는 직전 유효값을 유지한다.
    @param update 이번 스냅샷의 필드별 유효값
    @param old 직전 유효값
    @return 합친 유효값
    """
    return Signals(
        speed_kph=_pick(update.speed_kph, old.speed_kph),
        gear=_pick(update.gear, old.gear),
        crash=_pick(update.crash, old.crash),
        approach_left=_pick(update.approach_left, old.approach_left),
        approach_right=_pick(update.approach_right, old.approach_right),
        fire=_pick(update.fire, old.fire),
        overtemp=_pick(update.overtemp, old.overtemp),
        adult=_pick(update.adult, old.adult),
        isofix_left=_pick(update.isofix_left, old.isofix_left),
        isofix_right=_pick(update.isofix_right, old.isofix_right),
        ignition_on=_pick(update.ignition_on, old.ignition_on),
        sensor_fault=_pick(update.sensor_fault, old.sensor_fault),
    )


def _pick[T](new: T | None, old: T) -> T:
    """!
    @brief 새 값이 있으면 새 값, 없으면(None) 직전 값을 고른다.
    @param new 새 값 또는 None
    @param old 직전 값
    @return 고른 값
    """
    return old if new is None else new
