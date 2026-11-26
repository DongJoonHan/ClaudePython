"""!
@brief U4 판정 중재 단위 테스트 (SWR-001~005, 008, 009, 017~019, SWD 7장).

우선순위 시험은 순위마다 단독으로 그 규칙만 거는 입력 조각을 정의하고,
두 조각을 합쳐 1~11순위의 55쌍을 모두 만든다 (SWR-019 수용 기준).
"""

import dataclasses
import itertools

import pytest

from childlock.arbitration import arbitrate
from childlock.model import (
    Action,
    ArbitrationInput,
    CrashStatus,
    DoorMemory,
    DriverCommand,
    Lock,
    Reason,
    Side,
    Signals,
    Source,
    State,
)

## 상태 결정표 우선순서 (조각을 합칠 때 더 높은 상태를 고른다)
STATE_ORDER = [State.EMERGENCY, State.DEGRADED, State.FAULT, State.OFF]


def cmd(side: str, action: str) -> DriverCommand:
    """!
    @brief 운전자 명령을 만든다.
    @param side left/right/all
    @param action lock/unlock
    @return 명령
    """
    return DriverCommand(Side(side), Action(action), Source.AVN)


def make_input(
    state: State = State.NORMAL,
    command: DriverCommand | None = None,
    prev: Lock = Lock.RELEASE,
    mem_left: DoorMemory | None = None,
    any_invalid: bool = False,
    now_us: int = 0,
    **values: object,
) -> ArbitrationInput:
    """!
    @brief 기본값(시동 ON, 정지, 위험 없음)에서 바꿀 값만 지정해 입력을 만든다.
    @return 중재 입력
    """
    base = {"ignition_on": True}
    base.update(values)
    return ArbitrationInput(
        values=dataclasses.replace(Signals(), **base),
        state=state,
        command=command,
        prev_left=prev,
        prev_right=prev,
        mem_left=mem_left if mem_left is not None else DoorMemory(),
        mem_right=DoorMemory(),
        any_invalid=any_invalid,
        now_us=now_us,
    )


# 순위별 입력 조각과 왼쪽 도어의 단독 기대값 (직전 출력 RELEASE)
FRAGMENTS: dict[int, dict[str, object]] = {
    1: {"state": State.EMERGENCY},
    2: {"state": State.DEGRADED},
    3: {"approach_left": True},
    4: {"state": State.FAULT, "sensor_fault": True},
    5: {"crash": CrashStatus.PENDING},
    6: {"state": State.OFF, "ignition_on": False},
    7: {"fire": True},
    8: {"isofix_left": True},
    9: {"speed_kph": 5.0},
    10: {"adult": True},
    11: {"command": cmd("left", "lock")},
}
ALONE: dict[int, tuple[Lock, Reason]] = {
    1: (Lock.RELEASE, Reason.CRASH_CONFIRMED),
    2: (Lock.RELEASE, Reason.INPUT_STALE),
    3: (Lock.LOCK, Reason.APPROACH_RISK_LOCK),
    4: (Lock.RELEASE, Reason.SENSOR_FAULT),
    6: (Lock.RELEASE, Reason.IGNITION_OFF),
    7: (Lock.RELEASE, Reason.FIRE_RELEASE),
    8: (Lock.LOCK, Reason.ISOFIX_LOCK),
    9: (Lock.LOCK, Reason.AUTO_LOCK_SPEED),
    10: (Lock.RELEASE, Reason.ADULT_PRESENT_RELEASE),
    11: (Lock.LOCK, Reason.DRIVER_LOCK),
}


def combine(*ranks: int) -> ArbitrationInput:
    """!
    @brief 여러 순위의 조각을 합쳐 입력을 만든다 (상태는 결정표 순서로 선택).
    @param ranks 합칠 순위
    @return 중재 입력
    """
    merged: dict[str, object] = {}
    states = []
    for r in ranks:
        frag = dict(FRAGMENTS[r])
        if "state" in frag:
            states.append(frag.pop("state"))
        merged.update(frag)
    state = next((s for s in STATE_ORDER if s in states), State.NORMAL)
    return make_input(state=state, **merged)


@pytest.mark.parametrize("rank", sorted(ALONE))
def test_each_rank_alone(rank):
    d = arbitrate(combine(rank)).left
    assert (d.lock, d.reason, d.rank) == (*ALONE[rank], rank)


def test_pending_alone_changes_nothing():
    d = arbitrate(combine(5)).left
    assert (d.lock, d.reason, d.rank) == (Lock.RELEASE, Reason.NO_CHANGE, 12)


@pytest.mark.parametrize(
    ("high", "low"), list(itertools.combinations(range(1, 12), 2))
)
def test_rule_pairs_higher_rank_wins(high, low):
    # SWR-019: 55쌍. 5순위(PENDING)는 아래 순위의 LOCK만 무효화한다
    d = arbitrate(combine(high, low)).left
    if high == 5:
        low_lock, low_reason = ALONE[low]
        if low_lock is Lock.LOCK:
            expected = (Lock.RELEASE, Reason.CRASH_PENDING, 5)
        else:
            expected = (low_lock, low_reason, low)
    else:
        expected = (*ALONE[high], high)
    assert (d.lock, d.reason, d.rank) == expected


def test_three_rule_pending_isofix_fire():
    # SWR-019 표 1행: 화재(7)가 QM 최상위라 RELEASE
    inp = make_input(crash=CrashStatus.PENDING, isofix_left=True, fire=True)
    d = arbitrate(inp)
    assert (d.left.lock, d.left.reason) == (Lock.RELEASE, Reason.FIRE_RELEASE)
    assert (d.right.lock, d.right.reason) == (Lock.RELEASE, Reason.FIRE_RELEASE)


def test_three_rule_pending_speed_driver_unlock():
    # SWR-019 표 2행: QM 최상위가 차속(9) LOCK이라 출력 유지
    inp = make_input(
        crash=CrashStatus.PENDING, speed_kph=5.0, command=cmd("all", "unlock")
    )
    d = arbitrate(inp)
    for door in (d.left, d.right):
        assert (door.lock, door.reason) == (Lock.RELEASE, Reason.CRASH_PENDING)


def test_three_rule_pending_isofix_adult():
    # SWR-019 표 3행: 왼쪽은 ISOFIX(8) LOCK이 최상위라 유지, 오른쪽은 성인 해제
    inp = make_input(crash=CrashStatus.PENDING, isofix_left=True, adult=True)
    d = arbitrate(inp)
    assert (d.left.lock, d.left.reason) == (Lock.RELEASE, Reason.CRASH_PENDING)
    assert (d.right.lock, d.right.reason) == (
        Lock.RELEASE,
        Reason.ADULT_PRESENT_RELEASE,
    )


def test_pending_does_not_relabel_plain_hold():
    # 12순위(유지)는 LOCK이어도 CRASH_PENDING으로 바꾸지 않는다
    d = arbitrate(make_input(crash=CrashStatus.PENDING, prev=Lock.LOCK)).left
    assert (d.lock, d.reason, d.rank) == (Lock.LOCK, Reason.NO_CHANGE, 12)


def test_pending_still_applies_driver_unlock():
    # CR-02: PENDING 중에도 운전자 unlock은 적용
    inp = make_input(
        crash=CrashStatus.PENDING, prev=Lock.LOCK, command=cmd("left", "unlock")
    )
    d = arbitrate(inp).left
    assert (d.lock, d.reason) == (Lock.RELEASE, Reason.DRIVER_RELEASE)


@pytest.mark.parametrize("side", ["left", "right", "all"])
@pytest.mark.parametrize("action", ["lock", "unlock"])
def test_driver_command_applies_only_to_selected_doors(side, action):
    # SWR-001·002·009
    prev = Lock.RELEASE if action == "lock" else Lock.LOCK
    d = arbitrate(make_input(prev=prev, command=cmd(side, action)))
    new = Lock.LOCK if action == "lock" else Lock.RELEASE
    reason = Reason.DRIVER_LOCK if action == "lock" else Reason.DRIVER_RELEASE
    left_hit = side in ("left", "all")
    right_hit = side in ("right", "all")
    assert d.left.lock is (new if left_hit else prev)
    assert d.right.lock is (new if right_hit else prev)
    assert d.left.reason is (reason if left_hit else Reason.NO_CHANGE)
    assert d.right.reason is (reason if right_hit else Reason.NO_CHANGE)


def test_no_rule_with_invalid_input_reports_input_invalid():
    d = arbitrate(make_input(any_invalid=True)).left
    assert (d.reason, d.rank) == (Reason.INPUT_INVALID, 12)


def test_overtemperature_release():
    d = arbitrate(make_input(overtemp=True, prev=Lock.LOCK)).left
    assert (d.lock, d.reason, d.rank) == (
        Lock.RELEASE,
        Reason.OVERTEMPERATURE_RELEASE,
        7,
    )


def test_right_door_rules_do_not_touch_left():
    # SWR-009: 오른쪽 접근위험·ISOFIX는 왼쪽에 영향 없음
    d = arbitrate(make_input(approach_right=True, isofix_right=True))
    assert (d.right.lock, d.right.reason) == (
        Lock.LOCK,
        Reason.APPROACH_RISK_LOCK,
    )
    assert (d.left.lock, d.left.reason) == (Lock.RELEASE, Reason.NO_CHANGE)
    d = arbitrate(make_input(isofix_right=True))
    assert (d.right.lock, d.right.reason) == (Lock.LOCK, Reason.ISOFIX_LOCK)
    assert d.left.reason is Reason.NO_CHANGE


def test_approach_first_unlock_records_suppression_time():
    inp = make_input(
        approach_left=True, command=cmd("left", "unlock"), now_us=1_000_000
    )
    d = arbitrate(inp).left
    assert (d.lock, d.reason) == (Lock.LOCK, Reason.APPROACH_RISK_LOCK)
    assert d.memory == DoorMemory(suppressed_at_us=1_000_000, override=False)


@pytest.mark.parametrize("side", ["left", "all"])
def test_approach_reentry_at_exactly_10s_is_override(side):
    # SWR-006: 10.0 s 정각은 인정, 출력은 LOCK 유지 (Q-01)
    mem = DoorMemory(suppressed_at_us=1_000_000)
    inp = make_input(
        approach_left=True,
        command=cmd(side, "unlock"),
        mem_left=mem,
        now_us=11_000_000,
    )
    d = arbitrate(inp).left
    assert (d.lock, d.reason) == (Lock.LOCK, Reason.OVERRIDE_REQUESTED)
    assert d.memory == DoorMemory(suppressed_at_us=1_000_000, override=True)


def test_approach_reentry_after_10s_starts_new_cycle():
    # SWR-006·Q-22: 10 s 초과는 새 첫 요청, override 초기화
    mem = DoorMemory(suppressed_at_us=1_000_000, override=True)
    inp = make_input(
        approach_left=True,
        command=cmd("left", "unlock"),
        mem_left=mem,
        now_us=11_000_001,
    )
    d = arbitrate(inp).left
    assert d.reason is Reason.APPROACH_RISK_LOCK
    assert d.memory == DoorMemory(suppressed_at_us=11_000_001, override=False)


def test_approach_without_unlock_reports_existing_override():
    mem = DoorMemory(suppressed_at_us=0, override=True)
    for command in (None, cmd("right", "unlock"), cmd("left", "lock")):
        inp = make_input(approach_left=True, mem_left=mem, command=command)
        d = arbitrate(inp).left
        assert (d.lock, d.reason) == (Lock.LOCK, Reason.OVERRIDE_REQUESTED)
        assert d.memory == mem


def test_approach_lock_applies_during_fault():
    # Q-17: 센서 고장 중에도 접근위험 도어는 LOCK, 다른 도어는 유지
    inp = make_input(state=State.FAULT, sensor_fault=True, approach_left=True)
    d = arbitrate(inp)
    assert (d.left.lock, d.left.reason) == (
        Lock.LOCK,
        Reason.APPROACH_RISK_LOCK,
    )
    assert (d.right.lock, d.right.reason) == (Lock.RELEASE, Reason.SENSOR_FAULT)


@pytest.mark.parametrize(
    ("ranks", "reason"),
    [
        ((2,), Reason.INPUT_STALE),
        ((4,), Reason.SENSOR_FAULT),
        ((5, 9), Reason.CRASH_PENDING),
        ((5, 8), Reason.CRASH_PENDING),
        ((2, 7), Reason.INPUT_STALE),
        ((4, 6), Reason.SENSOR_FAULT),
    ],
)
def test_hold_rules_keep_previous_lock(ranks, reason):
    # CR-01: 2·4·5순위는 직전 출력이 LOCK이면 LOCK을 유지해야 한다
    # (직전 RELEASE로만 시험하면 "유지"와 "해제"를 구별하지 못한다)
    inp = dataclasses.replace(
        combine(*ranks), prev_left=Lock.LOCK, prev_right=Lock.LOCK
    )
    d = arbitrate(inp).left
    assert (d.lock, d.reason) == (Lock.LOCK, reason)
