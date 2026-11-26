"""!
@brief C4 판정 중재기: 우선순위표에 따라 도어별 출력과 reason을 정한다.

SWD-ECL-001 7장 (SWR-001~005, 008, 009, 017~019). 내부 상태가 없는 순수
함수다. 할당 ASIL B 규칙(1~5순위)을 QM 규칙(6~11순위)보다 먼저 검사한다.
"""

from collections.abc import Callable

from childlock.model import (
    AUTO_LOCK_SPEED_KPH,
    OVERRIDE_WINDOW_US,
    Action,
    ArbitrationInput,
    CrashStatus,
    Decision,
    Door,
    DoorDecision,
    DoorMemory,
    DriverCommand,
    Lock,
    Reason,
    Side,
    Signals,
    State,
)

## 도어 → 해당 도어를 가리키는 명령 side
_SIDE_OF = {Door.LEFT: Side.LEFT, Door.RIGHT: Side.RIGHT}

## 6~10순위 규칙표의 항목 타입: (조건, 출력, 이유, 순위)
_QmRule = tuple[Callable[[Door, Signals], bool], Lock, Reason, int]


def arbitrate(inp: ArbitrationInput) -> Decision:
    """!
    @brief 좌/우 도어를 각각 중재한다 (SWR-009 좌/우 독립).
    @param inp 중재 입력
    @return 중재 결과
    """
    return Decision(
        left=_decide_door(Door.LEFT, inp),
        right=_decide_door(Door.RIGHT, inp),
    )


def _decide_door(door: Door, inp: ArbitrationInput) -> DoorDecision:
    """!
    @brief 1~5순위(ASIL B)를 검사하고, 나머지는 QM 규칙에 맡긴다.
    @param door 대상 도어
    @param inp 중재 입력
    @return 도어 중재 결과
    """
    prev = inp.prev_left if door is Door.LEFT else inp.prev_right
    mem = inp.mem_left if door is Door.LEFT else inp.mem_right
    if inp.state is State.EMERGENCY:
        return DoorDecision(Lock.RELEASE, Reason.CRASH_CONFIRMED, 1, mem)
    if inp.state is State.DEGRADED:
        return DoorDecision(prev, Reason.INPUT_STALE, 2, mem)
    if _approach_risk(door, inp.values):
        return _approach(door, inp, mem)
    if inp.state is State.FAULT:
        return DoorDecision(prev, Reason.SENSOR_FAULT, 4, mem)
    qm = _decide_qm(door, inp, prev, mem)
    pending = inp.values.crash is CrashStatus.PENDING
    if pending and qm.rank <= 11 and qm.lock is Lock.LOCK:
        # 5순위: QM 최상위 결과가 LOCK이면 유지 (CR-02)
        # 아래 순위로 넘어가지 않는다
        return DoorDecision(prev, Reason.CRASH_PENDING, 5, mem)
    return qm


def _approach(
    door: Door, inp: ArbitrationInput, mem: DoorMemory
) -> DoorDecision:
    """!
    @brief 3순위: 접근위험 도어를 잠그고 해제 요청을 억제·override 판정한다.
    @param door 대상 도어
    @param inp 중재 입력
    @param mem 도어 기억
    @return 도어 중재 결과 (출력은 항상 LOCK, Q-01)
    """
    if not _targets_unlock(door, inp.command):
        reason = (
            Reason.OVERRIDE_REQUESTED
            if mem.override
            else Reason.APPROACH_RISK_LOCK
        )
        return DoorDecision(Lock.LOCK, reason, 3, mem)
    since = mem.suppressed_at_us
    if since is not None and inp.now_us - since <= OVERRIDE_WINDOW_US:
        new_mem = DoorMemory(suppressed_at_us=since, override=True)
        return DoorDecision(Lock.LOCK, Reason.OVERRIDE_REQUESTED, 3, new_mem)
    # 첫 요청 또는 10 s 초과: 새 주기 시작, override 초기화 (Q-22)
    new_mem = DoorMemory(suppressed_at_us=inp.now_us, override=False)
    return DoorDecision(Lock.LOCK, Reason.APPROACH_RISK_LOCK, 3, new_mem)


def _decide_qm(
    door: Door, inp: ArbitrationInput, prev: Lock, mem: DoorMemory
) -> DoorDecision:
    """!
    @brief 6~10순위 규칙표를 적용하고, 맞는 규칙이 없으면 명령을 처리한다.
    @param door 대상 도어
    @param inp 중재 입력
    @param prev 직전 출력
    @param mem 도어 기억
    @return 도어 중재 결과
    """
    for condition, lock, reason, rank in _QM_RULES:
        if condition(door, inp.values):
            return DoorDecision(lock, reason, rank, mem)
    return _decide_command(door, inp, prev, mem)


def _decide_command(
    door: Door, inp: ArbitrationInput, prev: Lock, mem: DoorMemory
) -> DoorDecision:
    """!
    @brief 11순위(운전자 명령)와 12순위(유지)를 처리한다.
    @param door 대상 도어
    @param inp 중재 입력
    @param prev 직전 출력
    @param mem 도어 기억
    @return 도어 중재 결과
    """
    cmd = inp.command
    if cmd is not None and _targets(door, cmd.side):
        if cmd.action is Action.LOCK:
            return DoorDecision(Lock.LOCK, Reason.DRIVER_LOCK, 11, mem)
        return DoorDecision(Lock.RELEASE, Reason.DRIVER_RELEASE, 11, mem)
    reason = Reason.INPUT_INVALID if inp.any_invalid else Reason.NO_CHANGE
    return DoorDecision(prev, reason, 12, mem)


def _targets(door: Door, side: Side) -> bool:
    """!
    @brief 명령 side가 도어를 가리키는지 판정한다.
    @param door 대상 도어
    @param side 명령 side
    @return side가 all이거나 도어와 같으면 True
    """
    return side is Side.ALL or side is _SIDE_OF[door]


def _targets_unlock(door: Door, cmd: DriverCommand | None) -> bool:
    """!
    @brief 명령이 이 도어를 대상으로 하는 unlock인지 판정한다.
    @param door 대상 도어
    @param cmd 명령 또는 None
    @return 해당하면 True
    """
    if cmd is None:
        return False
    return cmd.action is Action.UNLOCK and _targets(door, cmd.side)


def _approach_risk(door: Door, values: Signals) -> bool:
    """!
    @brief 도어별 접근위험 유효값을 고른다.
    @param door 대상 도어
    @param values 유효값
    @return 접근위험 여부
    """
    return values.approach_left if door is Door.LEFT else values.approach_right


def _isofix(door: Door, values: Signals) -> bool:
    """!
    @brief 도어별 ISOFIX 유효값을 고른다.
    @param door 대상 도어
    @param values 유효값
    @return ISOFIX 연결 여부
    """
    return values.isofix_left if door is Door.LEFT else values.isofix_right


## 6~10순위 규칙표. 위에서부터 처음 맞는 규칙을 쓴다 (SWR-019)
_QM_RULES: tuple[_QmRule, ...] = (
    (lambda _d, v: not v.ignition_on, Lock.RELEASE, Reason.IGNITION_OFF, 6),
    (lambda _d, v: v.fire, Lock.RELEASE, Reason.FIRE_RELEASE, 7),
    (lambda _d, v: v.overtemp, Lock.RELEASE, Reason.OVERTEMPERATURE_RELEASE, 7),
    (_isofix, Lock.LOCK, Reason.ISOFIX_LOCK, 8),
    (
        lambda _d, v: v.speed_kph >= AUTO_LOCK_SPEED_KPH,
        Lock.LOCK,
        Reason.AUTO_LOCK_SPEED,
        9,
    ),
    (lambda _d, v: v.adult, Lock.RELEASE, Reason.ADULT_PRESENT_RELEASE, 10),
)
