"""!
@brief SWE.6 SIL 시험: SWR-016 결정론적 재생 (1,000회).

고정 시계로 만든 입력 벡터를 새 인스턴스에서 1,000회 재생하고, 모든 틱의
SWRS 3.3 출력 전체를 순서대로 직렬화한 SHA-256 해시가 모두 같은지 본다.
"""

import hashlib
import json

from childlock.controller import ChildLockController

## 재생 횟수 (SWR-016 수용 기준)
REPLAYS = 1000


def build_vector() -> list[tuple[float, dict[str, object] | None]]:
    """!
    @brief 모든 우선순위 규칙과 무입력 틱이 섞인 200틱 입력 벡터를 만든다.
    @return (now_s, snapshot 또는 None) 목록
    """
    vector: list[tuple[float, dict[str, object] | None]] = []
    for n in range(200):
        if n % 17 == 16:
            vector.append((n / 100, None))  # 무입력 틱
            continue
        snap: dict[str, object] = {
            "timestamp_s": n / 100,
            "vehicle_speed_kph": float((n * 7) % 60),
            "gear": "D",
            "crash_status": ["NONE", "NONE", "PENDING"][n % 3],
            "rear_left_approach_risk": n % 11 < 3,
            "rear_right_approach_risk": n % 13 < 2,
            "fire_detected": n % 50 == 25,
            "overtemperature_detected": n % 70 == 35,
            "adult_present": n % 23 == 0,
            "isofix_left": n % 29 < 5,
            "isofix_right": False,
            "ignition_on": n % 90 < 80,
            "sensor_fault": n % 61 == 30,
        }
        if n % 5 == 0:
            snap["driver_command"] = {
                "side": ["left", "right", "all"][n % 3],
                "action": ["lock", "unlock"][n % 2],
                "source": "voice",
            }
        if n == 150:
            snap["crash_status"] = "CONFIRMED"
        vector.append((n / 100, snap))
    return vector


def replay_hash(vector: list[tuple[float, dict[str, object] | None]]) -> str:
    """!
    @brief 새 제어기로 벡터를 재생하고 출력 전체의 해시를 구한다.
    @param vector 입력 벡터
    @return SHA-256 16진 문자열
    """
    controller = ChildLockController()
    digest = hashlib.sha256()
    for now_s, snap in vector:
        out = controller.tick(now_s, snap)
        digest.update(json.dumps(out.to_dict(), sort_keys=True).encode())
    return digest.hexdigest()


def test_swr016_thousand_replays_give_identical_hash():
    vector = build_vector()
    first = replay_hash(vector)
    hashes = {replay_hash(vector) for _ in range(REPLAYS - 1)}
    assert hashes == {first}


def test_vector_exercises_many_states():
    # 벡터가 결정론 시험으로서 의미가 있도록 여러 상태를 지나는지 확인
    controller = ChildLockController()
    states = {controller.tick(t, s).state for t, s in build_vector()}
    assert {"NORMAL", "OFF", "FAULT", "EMERGENCY"} <= states
