"""!
@brief C6 제어기: 틱 진행, 출력 조립, 기록 조건, 상태 조회.

SWD-ECL-001 9장 (SWR-010, 013~016, 019~021, DD-01). 한 틱의 계산은 새 상태를
모두 만든 뒤 마지막 반영 단계에서 한 번에 바꾼다(AP-03).
"""

import math

from childlock.arbitration import arbitrate
from childlock.event_log import EventLog
from childlock.model import (
    INITIAL_OUTPUT,
    NOW_MAX_S,
    US_PER_S,
    ArbitrationInput,
    Decision,
    DecisionRecord,
    InputValidity,
    Output,
    SignalView,
    State,
    TickRejectedError,
    WarningCode,
)
from childlock.safety_state import SafetyState, advance_safety, apply_memory
from childlock.signals import TrackerState, advance_signals, initial_tracker
from childlock.validation import validate_snapshot

## 기록 조건에서 "바뀐 것"으로 보는 출력 필드 (SWR-010, CR-03)
_RecordKey = tuple[str, str, bool, bool, str]


class ChildLockController:
    """!@brief 전자식 차일드락 제어 SW의 진입점 (C6)."""

    def __init__(self) -> None:
        """!@brief 시작 상태: RELEASE/OFF, 기록 0건 (SWR-020)."""
        self._last_now_us: int | None = None
        self._tracker: TrackerState | None = None
        self._safety = SafetyState()
        self._output = INITIAL_OUTPUT
        self._log = EventLog()

    def tick(self, now_s: object, snapshot: object = None) -> Output:
        """!
        @brief 한 평가주기를 판정한다.
        @param now_s SW 시계 (초, 0~1e9, 1 µs 단위로 증가해야 함)
        @param snapshot VehicleSnapshot dict 또는 None(입력 없음)
        @return 이번 틱 출력
        @raises TickRejectedError now_s 사전조건 위반 (DD-01)
        """
        now_value, now_us = _to_now_us(now_s, self._last_now_us)
        parsed = validate_snapshot(snapshot)
        tracker = self._tracker
        if tracker is None:
            tracker = initial_tracker(now_us)
        tracker, view = advance_signals(tracker, parsed, now_us)
        safety, state = advance_safety(self._safety, view, now_us)
        decision = arbitrate(
            _arbitration_input(view, state, safety, self._output, now_us)
        )
        safety = apply_memory(safety, decision)
        output = _build_output(decision, state, view, safety)
        # 반영 단계 (AP-03): 여기부터 self를 바꾼다
        record = parsed.present or _record_key(output) != _record_key(
            self._output
        )
        self._last_now_us = now_us
        self._tracker = tracker
        self._safety = safety
        self._output = output
        if record:
            self._log.append(output, now_value)
        return output

    def status(self) -> Output:
        """!
        @brief 마지막 틱의 출력을 돌려준다 (SWR-014).
        @return 현재 출력
        """
        return self._output

    def events(self) -> tuple[DecisionRecord, ...]:
        """!
        @brief 최근 결정 기록을 돌려준다 (SWR-012).
        @return 기록 튜플 (event_id 오름차순)
        """
        return self._log.records()


def _to_now_us(now_s: object, last_us: int | None) -> tuple[float, int]:
    """!
    @brief now_s 사전조건을 검사하고 정수 µs로 바꾼다 (DD-01, DR-02).
    @param now_s 원시 시각
    @param last_us 직전 틱 시각 (µs) 또는 None
    @return (검증된 시각 float, 현재 틱 시각 µs)
    @raises TickRejectedError 사전조건 위반
    """
    if isinstance(now_s, bool) or not isinstance(now_s, int | float):
        raise TickRejectedError("now_s는 수여야 한다")
    if isinstance(now_s, float) and not math.isfinite(now_s):
        raise TickRejectedError("now_s는 유한해야 한다")
    if not 0 <= now_s <= NOW_MAX_S:
        raise TickRejectedError("now_s는 0~1e9 범위여야 한다")
    now_us = round(now_s * US_PER_S)
    if last_us is not None and now_us <= last_us:
        raise TickRejectedError("now_s는 1 µs 단위로 증가해야 한다")
    return float(now_s), now_us


def _arbitration_input(
    view: SignalView,
    state: State,
    safety: SafetyState,
    prev: Output,
    now_us: int,
) -> ArbitrationInput:
    """!
    @brief 중재 입력을 조립한다.
    @param view 신호 보기
    @param state 이번 틱 상태
    @param safety 기억이 정리된 안전 상태
    @param prev 직전 출력
    @param now_us 현재 틱 시각 (µs)
    @return 중재 입력
    """
    return ArbitrationInput(
        values=view.values,
        state=state,
        command=view.command,
        prev_left=prev.lock_left,
        prev_right=prev.lock_right,
        mem_left=safety.mem_left,
        mem_right=safety.mem_right,
        any_invalid=view.any_invalid,
        now_us=now_us,
    )


def _build_output(
    decision: Decision, state: State, view: SignalView, safety: SafetyState
) -> Output:
    """!
    @brief 중재 결과로 SWRS 3.3절 출력을 만든다.
    @param decision 중재 결과
    @param state 이번 틱 상태
    @param view 신호 보기
    @param safety 기억이 반영된 안전 상태
    @return 출력
    """
    left, right = decision.left, decision.right
    # 순위 값이 작을수록 우선. 같으면 왼쪽 (SWRS 3.3)
    priority = left if left.rank <= right.rank else right
    return Output(
        lock_left=left.lock,
        lock_right=right.lock,
        state=state,
        override_left=safety.mem_left.override,
        override_right=safety.mem_right.override,
        input_validity=_input_validity(view),
        reason_left=left.reason,
        reason_right=right.reason,
        priority_reason=priority.reason,
        reason_code=priority.reason,
        warning_code=(
            WarningCode.SENSOR_FAULT
            if view.values.sensor_fault
            else WarningCode.NONE
        ),
    )


def _input_validity(view: SignalView) -> InputValidity:
    """!
    @brief 입력 유효성 표시를 정한다 (STALE이 INVALID보다 우선).
    @param view 신호 보기
    @return 입력 유효성
    """
    if view.stale:
        return InputValidity.STALE
    if view.any_invalid:
        return InputValidity.INVALID
    return InputValidity.VALID


def _record_key(output: Output) -> _RecordKey:
    """!
    @brief 기록 조건 비교에 쓰는 출력 필드를 뽑는다 (SWR-010 조건 2).
    @param output 출력
    @return (lock_left, lock_right, override_left, override_right, state)
    """
    return (
        output.lock_left,
        output.lock_right,
        output.override_left,
        output.override_right,
        output.state,
    )
