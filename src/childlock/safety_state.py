"""!
@brief C3 안전 상태 관리기: EMERGENCY 래치, 상태 결정표, override 기억 정리.

SWD-ECL-001 6장 (SWR-005~007, 009, 013, 020, 021). 순수 함수로 새 상태를
만들고, 반영은 제어기(C6)가 한다(AP-03).
"""

import dataclasses
from dataclasses import dataclass, field

from childlock.model import (
    LATCH_RELEASE_US,
    CrashStatus,
    Decision,
    DoorMemory,
    SignalView,
    State,
)

## 래치 해제 시간을 셀 때 최신이어야 하는 필드 (RV-25)
_RELEASE_FIELDS = frozenset({"ignition_on", "crash"})
## 도어 기억(억제 시각, override)을 비우는 상태 (SWR-006, Q-24)
_CLEARING_STATES = frozenset({State.OFF, State.EMERGENCY})


@dataclass(frozen=True)
class SafetyState:
    """!@brief 안전 상태 관리기 내부 상태 (C6이 보관)."""

    latched: bool = False
    release_since_us: int | None = None
    mem_left: DoorMemory = field(default_factory=DoorMemory)
    mem_right: DoorMemory = field(default_factory=DoorMemory)


def determine_state(
    latched: bool, stale: bool, sensor_fault: bool, ignition_on: bool
) -> State:
    """!
    @brief SWRS 4장 상태 결정표를 위에서부터 적용한다.
    @param latched EMERGENCY 래치 여부
    @param stale 갱신 지연 여부
    @param sensor_fault sensor_fault 유효값
    @param ignition_on ignition_on 유효값
    @return 상태
    """
    if latched:
        return State.EMERGENCY
    if stale:
        return State.DEGRADED
    if sensor_fault:
        return State.FAULT
    if not ignition_on:
        return State.OFF
    return State.NORMAL


def advance_safety(
    state: SafetyState, view: SignalView, now_us: int
) -> tuple[SafetyState, State]:
    """!
    @brief 래치를 갱신하고 상태를 정한 뒤 override 기억을 정리한다.
    @param state 직전 안전 상태
    @param view 이번 틱의 신호 보기
    @param now_us 현재 틱 시각 (µs)
    @return (새 안전 상태, 이번 틱 상태)
    """
    latched, since = _update_latch(state, view, now_us)
    values = view.values
    st = determine_state(
        latched, view.stale, values.sensor_fault, values.ignition_on
    )
    new_state = SafetyState(
        latched=latched,
        release_since_us=since,
        mem_left=_clear_memory(state.mem_left, values.approach_left, st),
        mem_right=_clear_memory(state.mem_right, values.approach_right, st),
    )
    return new_state, st


def apply_memory(
    state: SafetyState, decision: Decision, st: State
) -> SafetyState:
    """!
    @brief 중재 결과의 도어 기억을 안전 상태에 넣는다.

    OFF·EMERGENCY 틱이 끝날 때는 기억이 비어 있어야 하므로 넣지 않는다
    (DI-02, CR-03, Q-24).
    @param state 안전 상태
    @param decision 중재 결과
    @param st 이번 틱 상태
    @return 기억이 갱신된 안전 상태
    """
    if st in _CLEARING_STATES:
        return dataclasses.replace(
            state, mem_left=DoorMemory(), mem_right=DoorMemory()
        )
    return dataclasses.replace(
        state, mem_left=decision.left.memory, mem_right=decision.right.memory
    )


def _update_latch(
    state: SafetyState, view: SignalView, now_us: int
) -> tuple[bool, int | None]:
    """!
    @brief EMERGENCY 래치를 설정·유지·해제한다 (SWR-007).
    @param state 직전 안전 상태
    @param view 이번 틱의 신호 보기
    @param now_us 현재 틱 시각 (µs)
    @return (래치 여부, 해제 조건 연속 성립 시작 시각)
    """
    if view.frame_confirmed or view.values.crash is CrashStatus.CONFIRMED:
        return True, None
    if not state.latched:
        return False, None
    release_ok = view.fresh >= _RELEASE_FIELDS and not view.values.ignition_on
    if not release_ok:
        # 조건이 끊기면 연속 시간을 처음부터 다시 센다
        return True, None
    since = state.release_since_us
    if since is None:
        since = now_us
    if now_us - since >= LATCH_RELEASE_US:
        return False, None
    return True, since


def _clear_memory(mem: DoorMemory, approach: bool, st: State) -> DoorMemory:
    """!
    @brief OFF·EMERGENCY이거나 접근위험 유효값이 FALSE이면 도어 기억을 지운다.
    @param mem 도어 기억
    @param approach 해당 도어 접근위험 유효값
    @param st 이번 틱 상태
    @return 정리된 도어 기억 (SWR-006, Q-20, Q-22, DR-03)
    """
    if st in _CLEARING_STATES or not approach:
        return DoorMemory()
    return mem
