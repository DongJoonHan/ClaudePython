"""!
@brief C0 공통 모델: 상수, 열거형, 구성요소 사이에 오가는 불변 타입.

SWD-ECL-001 3장. 구성요소 C1~C5는 이 모듈에만 의존한다(SWA-ECL-001 2.2).
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from types import MappingProxyType

# ---------------------------------------------------------------- 상수
## 자동 잠금 차속 임계값 (SWR-003)
AUTO_LOCK_SPEED_KPH = 3.0
## 차속 유효 범위 (OEM-IF-001)
SPEED_MIN_KPH = 0.0
SPEED_MAX_KPH = 300.0
## now_s 상한 (DD-01)
NOW_MAX_S = 1e9
## 초 → 마이크로초 (DD-05)
US_PER_S = 1_000_000
## 갱신 지연 한계 200 ms (SWR-013)
STALE_LIMIT_US = 200_000
## override 인정 창 10 s (SWR-006)
OVERRIDE_WINDOW_US = 10_000_000
## EMERGENCY 래치 해제 조건 지속 1 s (SWR-007)
LATCH_RELEASE_US = 1_000_000
## 결정 기록 보존 건수 (SWR-012)
EVENT_LOG_CAPACITY = 100
## HTTP 요청 본문 상한 64 KiB (DD-03)
MAX_BODY_BYTES = 65_536
## 상한을 넘는 본문을 400 응답 전에 읽어서 버리는 최대 크기 8 MiB (DD-03, CR-05)
MAX_DISCARD_BYTES = 8 * 1024 * 1024
## Content-Length 헤더의 최대 자릿수 (DD-03, CR-02)
MAX_LENGTH_DIGITS = 10
## HTTP 요청 소켓 제한 시간 (DD-07, CR-04)
REQUEST_TIMEOUT_S = 5.0


# ---------------------------------------------------------------- 열거형
class Lock(StrEnum):
    """!@brief 차일드락 논리 출력 (OEM-IF-005)."""

    LOCK = "LOCK"
    RELEASE = "RELEASE"


class State(StrEnum):
    """!@brief SW 상태 (SWRS 4장 상태 결정표)."""

    OFF = "OFF"
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    FAULT = "FAULT"
    EMERGENCY = "EMERGENCY"


class InputValidity(StrEnum):
    """!@brief 입력 유효성 표시 (SWRS 3.3)."""

    VALID = "VALID"
    INVALID = "INVALID"
    STALE = "STALE"


class WarningCode(StrEnum):
    """!@brief 경고 코드 (SWR-021)."""

    NONE = "NONE"
    SENSOR_FAULT = "SENSOR_FAULT"


class Reason(StrEnum):
    """!@brief 판정 이유 코드 (SWRS 3.4)."""

    CRASH_CONFIRMED = "CRASH_CONFIRMED"
    INPUT_STALE = "INPUT_STALE"
    APPROACH_RISK_LOCK = "APPROACH_RISK_LOCK"
    OVERRIDE_REQUESTED = "OVERRIDE_REQUESTED"
    SENSOR_FAULT = "SENSOR_FAULT"
    CRASH_PENDING = "CRASH_PENDING"
    IGNITION_OFF = "IGNITION_OFF"
    FIRE_RELEASE = "FIRE_RELEASE"
    OVERTEMPERATURE_RELEASE = "OVERTEMPERATURE_RELEASE"
    ISOFIX_LOCK = "ISOFIX_LOCK"
    AUTO_LOCK_SPEED = "AUTO_LOCK_SPEED"
    ADULT_PRESENT_RELEASE = "ADULT_PRESENT_RELEASE"
    DRIVER_LOCK = "DRIVER_LOCK"
    DRIVER_RELEASE = "DRIVER_RELEASE"
    INPUT_INVALID = "INPUT_INVALID"
    NO_CHANGE = "NO_CHANGE"


class Gear(StrEnum):
    """!@brief 기어 위치 (OEM-IF-001). 형식 검사만 하고 판정에 쓰지 않는다."""

    P = "P"
    N = "N"
    D = "D"
    R = "R"


class CrashStatus(StrEnum):
    """!@brief 충돌 상태 (OEM-IF-002)."""

    NONE = "NONE"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"


class Side(StrEnum):
    """!@brief 운전자 명령 대상 (OEM-IF-004)."""

    LEFT = "left"
    RIGHT = "right"
    ALL = "all"


class Action(StrEnum):
    """!@brief 운전자 명령 동작 (OEM-IF-004)."""

    LOCK = "lock"
    UNLOCK = "unlock"


class Source(StrEnum):
    """!@brief 운전자 명령 경로 (OEM-IF-004)."""

    PHYSICAL_BUTTON = "physical_button"
    AVN = "avn"
    VOICE = "voice"
    MOBILE_APP = "mobile_app"


class Door(StrEnum):
    """!@brief 후석 도어 (내부용)."""

    LEFT = "LEFT"
    RIGHT = "RIGHT"


## 입력 키 → Signals 필드 이름 (SWRS 3.1)
FIELD_MAP: Mapping[str, str] = MappingProxyType(
    {
        "vehicle_speed_kph": "speed_kph",
        "gear": "gear",
        "crash_status": "crash",
        "rear_left_approach_risk": "approach_left",
        "rear_right_approach_risk": "approach_right",
        "fire_detected": "fire",
        "overtemperature_detected": "overtemp",
        "adult_present": "adult",
        "isofix_left": "isofix_left",
        "isofix_right": "isofix_right",
        "ignition_on": "ignition_on",
        "sensor_fault": "sensor_fault",
    }
)
## 갱신 지연을 감시하는 판정 필드 11개 (gear 제외, SWR-013)
DECISION_FIELDS: tuple[str, ...] = tuple(
    name for name in FIELD_MAP.values() if name != "gear"
)


# ---------------------------------------------------------------- 불변 타입
@dataclass(frozen=True)
class DriverCommand:
    """!@brief 유효한 운전자 명령 (SWRS 3.2)."""

    side: Side
    action: Action
    source: Source


@dataclass(frozen=True)
class Signals:
    """!@brief 판정에 쓰는 필드별 유효값. 기본값은 초기 유효값(SWRS 3.1)."""

    speed_kph: float = 0.0
    gear: Gear = Gear.P
    crash: CrashStatus = CrashStatus.NONE
    approach_left: bool = False
    approach_right: bool = False
    fire: bool = False
    overtemp: bool = False
    adult: bool = False
    isofix_left: bool = False
    isofix_right: bool = False
    ignition_on: bool = False
    sensor_fault: bool = False


@dataclass(frozen=True)
class SignalUpdate:
    """!@brief 한 스냅샷의 필드별 유효값. None은 누락 또는 오류."""

    speed_kph: float | None = None
    gear: Gear | None = None
    crash: CrashStatus | None = None
    approach_left: bool | None = None
    approach_right: bool | None = None
    fire: bool | None = None
    overtemp: bool | None = None
    adult: bool | None = None
    isofix_left: bool | None = None
    isofix_right: bool | None = None
    ignition_on: bool | None = None
    sensor_fault: bool | None = None


@dataclass(frozen=True)
class ParsedInput:
    """!@brief C1 검증 결과 (C1 → C2)."""

    present: bool
    timestamp: float | None = None
    update: SignalUpdate = SignalUpdate()
    invalid_fields: frozenset[str] = frozenset()
    command: DriverCommand | None = None
    command_invalid: bool = False


@dataclass(frozen=True)
class SignalView:
    """!@brief C2 판정용 신호 보기 (C2 → C3, C4, C6)."""

    values: Signals
    stale: bool
    fresh: frozenset[str]
    order_valid: bool
    frame_confirmed: bool
    any_invalid: bool
    command: DriverCommand | None


@dataclass(frozen=True)
class DoorMemory:
    """!@brief 도어별 접근위험 억제 시각과 override (SWR-005, 006)."""

    suppressed_at_us: int | None = None
    override: bool = False


@dataclass(frozen=True)
class ArbitrationInput:
    """!@brief C4 중재 입력 (C6 → C4)."""

    values: Signals
    state: State
    command: DriverCommand | None
    prev_left: Lock
    prev_right: Lock
    mem_left: DoorMemory
    mem_right: DoorMemory
    any_invalid: bool
    now_us: int


@dataclass(frozen=True)
class DoorDecision:
    """!@brief 도어 하나의 중재 결과."""

    lock: Lock
    reason: Reason
    rank: int
    memory: DoorMemory


@dataclass(frozen=True)
class Decision:
    """!@brief 좌/우 중재 결과 (C4 → C6)."""

    left: DoorDecision
    right: DoorDecision


@dataclass(frozen=True)
class Output:
    """!@brief 틱 출력 (SWRS 3.3)."""

    lock_left: Lock
    lock_right: Lock
    state: State
    override_left: bool
    override_right: bool
    input_validity: InputValidity
    reason_left: Reason
    reason_right: Reason
    priority_reason: Reason
    reason_code: Reason
    warning_code: WarningCode

    def to_dict(self) -> dict[str, str | bool | int | float]:
        """!
        @brief JSON 직렬화용 dict로 바꾼다.
        @return SWRS 필드 이름 → 값 (열거형은 문자열)
        """
        return {k: _plain(v) for k, v in asdict(self).items()}


@dataclass(frozen=True)
class DecisionRecord:
    """!@brief 결정 기록 (SWR-011 허용 필드만)."""

    event_id: int
    now_s: float
    state: State
    lock_left: Lock
    lock_right: Lock
    override_left: bool
    override_right: bool
    input_validity: InputValidity
    reason_left: Reason
    reason_right: Reason
    priority_reason: Reason
    warning_code: WarningCode

    @classmethod
    def from_output(
        cls, event_id: int, now_s: float, out: Output
    ) -> "DecisionRecord":
        """!
        @brief 출력에서 허용 필드만 복사해 기록을 만든다.
        @param event_id 고유 식별자
        @param now_s 틱 시각 (호출자가 넘긴 값)
        @param out 틱 출력
        @return 결정 기록
        """
        return cls(
            event_id=event_id,
            now_s=now_s,
            state=out.state,
            lock_left=out.lock_left,
            lock_right=out.lock_right,
            override_left=out.override_left,
            override_right=out.override_right,
            input_validity=out.input_validity,
            reason_left=out.reason_left,
            reason_right=out.reason_right,
            priority_reason=out.priority_reason,
            warning_code=out.warning_code,
        )

    def to_dict(self) -> dict[str, str | bool | int | float]:
        """!
        @brief JSON 직렬화용 dict로 바꾼다.
        @return 필드 이름 → 값 (열거형은 문자열)
        """
        return {k: _plain(v) for k, v in asdict(self).items()}


def _plain(value: object) -> str | bool | int | float:
    """!
    @brief 열거형은 문자열로, 나머지 기본형은 그대로 돌려준다.
    @param value 필드 값
    @return JSON 기본형 값
    """
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, bool | int | float):
        return value
    raise TypeError(f"직렬화할 수 없는 값: {type(value).__name__}")


class TickRejectedError(ValueError):
    """!@brief 틱 사전조건 위반 (DD-01). Web에서는 400으로 바뀐다."""


## 시작 시 출력 (SWR-020: RELEASE/OFF, reason IGNITION_OFF)
INITIAL_OUTPUT = Output(
    lock_left=Lock.RELEASE,
    lock_right=Lock.RELEASE,
    state=State.OFF,
    override_left=False,
    override_right=False,
    input_validity=InputValidity.VALID,
    reason_left=Reason.IGNITION_OFF,
    reason_right=Reason.IGNITION_OFF,
    priority_reason=Reason.IGNITION_OFF,
    reason_code=Reason.IGNITION_OFF,
    warning_code=WarningCode.NONE,
)
