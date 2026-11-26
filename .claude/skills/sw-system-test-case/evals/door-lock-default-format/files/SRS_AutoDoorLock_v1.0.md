# SW 요구사항 명세서 — BCM 자동 도어 잠금 (v1.0)

대상: Body Control Module SW / ASIL: QM~A

## 입력 신호
| 신호 | 범위 | 분해능 | 주기 | 비고 |
|---|---|---|---|---|
| VehicleSpeed | 0 ~ 255 km/h | 0.1 km/h | 20 ms (CAN) | 0xFFFF = Invalid |
| GearPosition | P, R, N, D | - | 20 ms (CAN) | |
| IgnitionState | OFF, ACC, ON, START | - | 10 ms | |
| DoorAjarStatus[FL,FR,RL,RR] | OPEN, CLOSED | - | 10 ms | 하드와이어 입력 |
| CrashSignal | NO_CRASH, CRASH | - | 10 ms (CAN) | |
| AutoLockSetting | ENABLE, DISABLE | - | - | NVM 저장 사용자 설정 |

## 출력
| 신호 | 값 |
|---|---|
| LockActuatorCmd | NONE, LOCK, UNLOCK (펄스 300 ms) |
| DoorLockStatus | LOCKED, UNLOCKED |

## 요구사항

**SWR-ADL-001** IgnitionState = ON 이고 AutoLockSetting = ENABLE 이며 모든 도어가 CLOSED 인 상태에서, VehicleSpeed 가 15.0 km/h 이상으로 2.0 s 이상 연속 유지되면 SW는 LockActuatorCmd = LOCK 을 1회 출력해야 한다.

**SWR-ADL-002** SWR-ADL-001 조건 중 하나의 도어라도 OPEN 이면 자동 잠금을 수행하지 않아야 한다.

**SWR-ADL-003** 자동 잠금 후 VehicleSpeed 가 다시 15.0 km/h 미만으로 떨어졌다가 재상승하더라도, IgnitionState 가 OFF 로 전환되기 전까지 자동 잠금을 재수행하지 않아야 한다.

**SWR-ADL-004** IgnitionState = ON 에서 GearPosition 이 P 로 변경되면 SW는 500 ms 이내에 LockActuatorCmd = UNLOCK 을 출력해야 한다 (AutoLockSetting = ENABLE 인 경우에 한함).

**SWR-ADL-005** CrashSignal = CRASH 수신 시, 다른 모든 조건과 무관하게 100 ms 이내에 LockActuatorCmd = UNLOCK 을 출력하고, 이후 10 s 동안 LOCK 명령을 금지해야 한다.

**SWR-ADL-006** VehicleSpeed 가 Invalid(0xFFFF) 이거나 200 ms 이상 수신되지 않으면 자동 잠금 판정을 중단하고 마지막 잠금 상태를 유지해야 한다.

**SWR-ADL-007** AutoLockSetting 변경은 IgnitionState = ON, VehicleSpeed < 3.0 km/h 에서만 수락되어야 하며, 수락된 설정은 다음 IGN 사이클에도 유지되어야 한다.

**SWR-ADL-008** (비기능) LockActuatorCmd 출력 후 DoorLockStatus 갱신은 400 ms 이내에 이루어져야 한다.

**SWR-ADL-009** (비기능) 자동 잠금 기능의 주기 태스크 실행 시간은 최악 조건에서 0.5 ms 를 초과하지 않아야 한다 (10 ms 태스크).

**SWR-ADL-010** (비기능) 자동 잠금 모듈 소스 코드는 MISRA C:2012 필수(Mandatory) 규칙을 위반하지 않아야 한다.
