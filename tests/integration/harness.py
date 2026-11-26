"""!
@brief 통합 시험 하네스: 10 ms 틱으로 차량 입력을 시간 순서대로 넣는다.

시각은 정수 틱 번호 n으로 관리하고 now_s = timestamp_s = n / 100으로 보낸다.
"""

from childlock.controller import ChildLockController
from childlock.model import Output


class Drive:
    """!@brief 시나리오 주행기. 차량 입력 상태를 유지하며 틱을 진행한다."""

    def __init__(self, **initial: object) -> None:
        """!
        @brief 기본 입력(시동 ON, 정지, 위험 없음)으로 시작한다.
        @param initial 바꿀 초기 입력
        """
        self.controller = ChildLockController()
        self.n = 0
        self.inputs: dict[str, object] = {
            "vehicle_speed_kph": 0.0,
            "gear": "P",
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
        self.inputs.update(initial)

    @property
    def now_s(self) -> float:
        """!@brief 현재 틱 시각(초)."""
        return self.n / 100

    def step(
        self,
        cmd: tuple[str, str] | None = None,
        source: str = "avn",
        timestamp_s: float | None = None,
        **changes: object,
    ) -> Output:
        """!
        @brief 입력을 바꾸고 스냅샷 한 건으로 한 틱 진행한다.
        @param cmd (side, action) 운전자 명령
        @param source 명령 경로
        @param timestamp_s 스냅샷 timestamp (기본: 현재 시각)
        @param changes 바꿀 차량 입력 (이후 틱에도 유지)
        @return 출력
        """
        self.inputs.update(changes)
        self.n += 1
        snap = dict(self.inputs)
        snap["timestamp_s"] = self.now_s if timestamp_s is None else timestamp_s
        if cmd is not None:
            snap["driver_command"] = {
                "side": cmd[0],
                "action": cmd[1],
                "source": source,
            }
        return self.controller.tick(self.now_s, snap)

    def run(self, ticks: int, **changes: object) -> Output:
        """!
        @brief 같은 입력으로 여러 틱 진행한다.
        @param ticks 틱 수
        @param changes 바꿀 차량 입력
        @return 마지막 출력
        """
        out = self.step(**changes)
        for _ in range(ticks - 1):
            out = self.step()
        return out

    def idle(self, ticks: int) -> Output:
        """!
        @brief 입력 없이 여러 틱 진행한다 (신호 끊김).
        @param ticks 틱 수
        @return 마지막 출력
        """
        out = self.controller.status()
        for _ in range(ticks):
            self.n += 1
            out = self.controller.tick(self.now_s)
        return out
