"""!
@brief U3 안전 상태 단위 테스트 (SWR-006, 007, 013, 020, 021, SWD 6장).
"""

import dataclasses

import pytest

from childlock.model import (
    DECISION_FIELDS,
    CrashStatus,
    Decision,
    DoorDecision,
    DoorMemory,
    Lock,
    Reason,
    Signals,
    SignalView,
    State,
)
from childlock.safety_state import (
    SafetyState,
    advance_safety,
    apply_memory,
    determine_state,
)

ALL_FRESH = frozenset(DECISION_FIELDS)


def view(
    fresh: frozenset[str] = ALL_FRESH,
    frame_confirmed: bool = False,
    **values: object,
) -> SignalView:
    """!
    @brief 테스트용 신호 보기를 만든다.
    @param fresh 최신 필드 집합 (stale은 이것으로 계산)
    @param frame_confirmed 이번 프레임 CONFIRMED 여부
    @param values Signals 필드 값
    @return 신호 보기
    """
    return SignalView(
        values=dataclasses.replace(Signals(), **values),
        stale=fresh != ALL_FRESH,
        fresh=fresh,
        order_valid=True,
        frame_confirmed=frame_confirmed,
        any_invalid=False,
        command=None,
    )


@pytest.mark.parametrize(
    ("latched", "stale", "fault", "ign", "expected"),
    [
        (True, True, True, False, State.EMERGENCY),
        (False, True, True, False, State.DEGRADED),
        (False, False, True, False, State.FAULT),
        (False, False, False, False, State.OFF),
        (False, False, False, True, State.NORMAL),
        (False, False, True, True, State.FAULT),
        (True, False, False, True, State.EMERGENCY),
    ],
)
def test_determine_state_follows_decision_table_order(
    latched, stale, fault, ign, expected
):
    # SWRS 4장: 위에서부터 처음 맞는 행
    assert determine_state(latched, stale, fault, ign) is expected


def test_frame_confirmed_sets_latch():
    st, state = advance_safety(SafetyState(), view(frame_confirmed=True), 0)
    assert st.latched is True
    assert state is State.EMERGENCY


def test_effective_confirmed_keeps_latch_even_with_ignition_off():
    latched = SafetyState(latched=True, release_since_us=5)
    st, _ = advance_safety(
        latched, view(crash=CrashStatus.CONFIRMED, ignition_on=False), 10
    )
    assert st.latched is True
    assert st.release_since_us is None


def test_latch_releases_after_exactly_one_second_of_fresh_ignition_off():
    # SWR-007: 0.99 s는 유지, 1.00 s는 해제
    st = SafetyState(latched=True)
    st, _ = advance_safety(st, view(ignition_on=False), 1_000_000)
    assert (st.latched, st.release_since_us) == (True, 1_000_000)
    st2, _ = advance_safety(st, view(ignition_on=False), 1_990_000)
    assert st2.latched is True
    st3, state3 = advance_safety(st2, view(ignition_on=False), 2_000_000)
    assert st3.latched is False
    assert st3.release_since_us is None
    assert state3 is State.OFF


def test_release_counting_starting_at_time_zero():
    # DR-05 회귀: 시작 시각 0을 None으로 착각하지 않는다
    st = SafetyState(latched=True)
    st, _ = advance_safety(st, view(ignition_on=False), 0)
    assert st.release_since_us == 0
    st, _ = advance_safety(st, view(ignition_on=False), 1_000_000)
    assert st.latched is False


def test_release_counting_restarts_when_ignition_turns_on():
    st = SafetyState(latched=True, release_since_us=0)
    st, _ = advance_safety(st, view(ignition_on=True), 500_000)
    assert (st.latched, st.release_since_us) == (True, None)


@pytest.mark.parametrize("missing", ["ignition_on", "crash"])
def test_release_not_counted_while_ignition_or_crash_is_stale(missing):
    # RV-25: 오래된 값으로 래치가 풀리지 않는다
    st = SafetyState(latched=True, release_since_us=0)
    st, state = advance_safety(
        st, view(fresh=ALL_FRESH - {missing}, ignition_on=False), 2_000_000
    )
    assert (st.latched, st.release_since_us) == (True, None)
    assert state is State.EMERGENCY


def test_no_latch_without_confirmed():
    st, state = advance_safety(SafetyState(), view(ignition_on=True), 0)
    assert (st.latched, st.release_since_us) == (False, None)
    assert state is State.NORMAL


def test_memory_cleared_when_state_is_off():
    mem = DoorMemory(suppressed_at_us=1, override=True)
    st = SafetyState(mem_left=mem, mem_right=mem)
    st, _ = advance_safety(
        st, view(ignition_on=False, approach_left=True, approach_right=True), 5
    )
    assert st.mem_left == DoorMemory()
    assert st.mem_right == DoorMemory()


def test_memory_kept_while_approach_risk_true_and_cleared_per_door():
    mem = DoorMemory(suppressed_at_us=1, override=True)
    st = SafetyState(mem_left=mem, mem_right=mem)
    st, _ = advance_safety(
        st, view(ignition_on=True, approach_left=True, approach_right=False), 5
    )
    assert st.mem_left == mem
    assert st.mem_right == DoorMemory()


def test_memory_cleared_by_valid_false_even_while_degraded():
    # DR-03 회귀: DEGRADED 중에도 접근위험 유효값 FALSE면 지운다
    mem = DoorMemory(suppressed_at_us=1, override=True)
    st = SafetyState(mem_left=mem)
    st, state = advance_safety(
        st,
        view(
            fresh=ALL_FRESH - {"speed_kph"},
            ignition_on=True,
            approach_left=False,
        ),
        5,
    )
    assert state is State.DEGRADED
    assert st.mem_left == DoorMemory()


def test_apply_memory_takes_memories_from_decision():
    new_l = DoorMemory(suppressed_at_us=9, override=False)
    new_r = DoorMemory(suppressed_at_us=3, override=True)
    decision = Decision(
        left=DoorDecision(Lock.LOCK, Reason.APPROACH_RISK_LOCK, 3, new_l),
        right=DoorDecision(Lock.LOCK, Reason.OVERRIDE_REQUESTED, 3, new_r),
    )
    st = apply_memory(SafetyState(latched=True), decision, State.NORMAL)
    assert (st.latched, st.mem_left, st.mem_right) == (True, new_l, new_r)


@pytest.mark.parametrize("st", [State.OFF, State.EMERGENCY])
def test_apply_memory_discards_new_memory_in_clearing_states(st):
    # CR-03, Q-24: OFF·EMERGENCY 틱이 끝날 때 기억은 비어 있다
    mem = DoorMemory(suppressed_at_us=9, override=True)
    decision = Decision(
        left=DoorDecision(Lock.LOCK, Reason.APPROACH_RISK_LOCK, 3, mem),
        right=DoorDecision(Lock.LOCK, Reason.APPROACH_RISK_LOCK, 3, mem),
    )
    out = apply_memory(SafetyState(), decision, st)
    assert (out.mem_left, out.mem_right) == (DoorMemory(), DoorMemory())
