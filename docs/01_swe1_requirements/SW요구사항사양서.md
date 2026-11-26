# SW 요구사항 사양서: 전자식 차일드락 제어 SW

| 항목 | 내용 |
|---|---|
| 문서 ID | SWRS-ECL-001 |
| 버전 | 1.0 (기준선 BL-SWR-1.0 후보) |
| 상위 문서 | OEM-SWR-001 OEM SW 요구사항 사양서 Rev 1.0 (BL-OEM-1.0) |
| 관련 문서 | QA-ECL-001 질의 및 가정 목록, UC-ECL-001 Use Case, TRC-ECL-001 추적성 매트릭스, RVW-ECL-001 검토 기록 |
| 프로세스 | A-SPICE SWE.1 |

| 버전 | 내용 |
|---|---|
| 0.1 | 초안 |
| 1.0 | 독립 검토 RV-01~RV-20, 재검토 RV-21~RV-23 반영 (RVW-ECL-001) |

## 1. 범위

후석 좌/우 전자식 차일드락의 잠금(LOCK)·해제(RELEASE) 판단, 상태, 판정 이유, 결정 기록을 만드는 SW를 정의한다. 실행 환경은 Python 3.12 PC/SIL이고, 표시·조작은 Web 시뮬레이터로 한다. 도어 래치, 구동기, 통신 드라이버, HMI 양산 승인은 범위 밖이다.

**ASIL 표기:** "할당 ASIL"은 OEM이 상위 요구에 부여한 분류를 그대로 물려받은 값이다. 개발 계획서 D-03에 따라 모든 요구는 실제로 ASIL B 수준의 엄격도로 개발·검증한다.

## 2. 실행 모델과 시간 기준

| 용어 | 정의 |
|---|---|
| SW 시계 (now_s) | SW에 주입되는 단조 증가 시각(초). SIL과 Web에서는 시험자가 제공하는 시뮬레이션 시각이다. 실제 벽시계를 쓰지 않는다 |
| 평가주기 (틱) | SW가 판정을 한 번 수행하는 단위. 10 ms 간격으로 호출된다고 가정한다 (Q-08). 틱마다 VehicleSnapshot이 0건 또는 1건 들어온다 |
| 반영 주기 | VehicleSnapshot이 들어온 바로 그 틱. 입력은 반영 주기의 출력에 반영된다. OEM 문서의 "다음 평가주기"와 "첫 평가주기"는 모두 반영 주기를 뜻한다 |
| 지연 | 반영 주기의 now_s에서 출력이 결정된 틱의 now_s까지의 시간 |
| 순서 유효 스냅샷 | timestamp_s가 유효하고, 직전 순서 유효 스냅샷의 timestamp_s보다 **엄격히 큰** VehicleSnapshot. 그렇지 않은 스냅샷(timestamp 오류, 과거·같은 시각의 재전송·역순 프레임)은 **순서 무효 스냅샷**이며, 차량 필드와 운전자 명령을 판정에 쓰지 않는다. crash_status=CONFIRMED만 예외다 (SWR-013, Q-21) |
| 판정 필드 | gear를 뺀 차량 필드 11개: vehicle_speed_kph, crash_status, rear_left/right_approach_risk, fire_detected, overtemperature_detected, adult_present, isofix_left/right, ignition_on, sensor_fault |
| 필드 갱신 시각 | 판정 필드마다 따로 관리한다. 순서 유효 스냅샷 안에서 그 필드가 유효하면, 그 틱의 now_s로 갱신한다. SW 시작 시에는 모든 필드를 시작 틱의 now_s로 초기화한다 |
| 확정 출력 | 직전 틱까지 SW가 내보낸 좌/우 LOCK·RELEASE 값 |
| 유효값 | 3.1절 규칙을 통과한 필드 값. 오류 필드는 그 필드의 직전 유효값으로 대체한다. 대체가 200 ms를 넘게 이어지면 갱신 지연이 된다 (SWR-013) |

## 3. 인터페이스 데이터

### 3.1 VehicleSnapshot (입력)

| 필드 | 형식 / 범위 | 출처 IF | 초기 유효값 |
|---|---|---|---|
| timestamp_s | 유한 실수(int 또는 float, bool 제외), 초 | OEM-IF-001 | 없음 |
| vehicle_speed_kph | 유한 실수(int 또는 float, bool 제외), 0.0~300.0 | OEM-IF-001 | 0.0 |
| gear | 문자열 P / N / D / R | OEM-IF-001 | P |
| crash_status | 문자열 NONE / PENDING / CONFIRMED | OEM-IF-002 | NONE |
| rear_left_approach_risk, rear_right_approach_risk | bool | OEM-IF-003 | FALSE |
| fire_detected, overtemperature_detected, adult_present | bool | OEM-IF-007 | FALSE |
| isofix_left, isofix_right | bool | OEM-IF-008 | FALSE |
| ignition_on, sensor_fault | bool | OEM-IF-009 | FALSE |
| driver_command | DriverCommand 또는 없음 | OEM-IF-004 | 없음 |

- **오류의 정의:** 필드 누락, 형식 불일치, 범위 밖 값, 목록 밖 값, NaN·무한대를 모두 오류로 본다. bool 필드에 `0`, `1`, 문자열이 오면 형식 오류이고, 숫자 필드에 `True`, `False`가 와도 형식 오류다.
- **gear:** 형식 검사만 하고 판정에는 쓰지 않는다. OEM 요구 중 기어를 조건으로 쓰는 요구가 없기 때문이다.
- **요청 시각:** 운전자 명령의 요청 시각은 별도 필드 없이 VehicleSnapshot의 timestamp_s를 쓴다 (OEM-IF-004).

### 3.2 DriverCommand (입력)

| 필드 | 값 |
|---|---|
| side | 문자열 left / right / all |
| action | 문자열 lock / unlock |
| source | 문자열 physical_button / avn / voice / mobile_app |

필드가 하나라도 누락되거나 형식·목록 오류이면 **그 명령만** 거절한다. 같은 VehicleSnapshot의 차량 신호 판정에는 영향을 주지 않는다.

### 3.3 출력 (틱마다 생성)

| 필드 | 값 | 출처 IF |
|---|---|---|
| lock_left, lock_right | LOCK / RELEASE | OEM-IF-005 |
| state | OFF / NORMAL / DEGRADED / FAULT / EMERGENCY (4장 상태 결정표) | OEM-IF-006 |
| override_left, override_right | bool | OEM-IF-006 |
| input_validity | VALID / INVALID / STALE | OEM-IF-006 |
| reason_left, reason_right | 도어별 출력을 결정한 규칙의 이유 코드 (3.4절) | OEM-IF-006 |
| priority_reason | 두 도어를 결정한 규칙 중 SWR-019 순위가 더 높은 규칙의 이유 코드. 같은 순위면 reason_left | OEM-IF-006 |
| reason_code | priority_reason과 같은 값 (OEM-IF-006 "priority_reason을 reason_code로도 매핑") | OEM-IF-006 |
| warning_code | sensor_fault 유효값이 TRUE이면 state와 관계없이 SENSOR_FAULT, 그 외에는 NONE | OEM-SR-004 |

- **input_validity:** 갱신 지연이면 STALE, 이번 틱의 입력에 오류 필드나 거절된 명령이 있으면 INVALID, 그 외에는 VALID이다. STALE이 INVALID보다 우선한다.

### 3.4 이유 코드

| 코드 | 의미 | 관련 SWR |
|---|---|---|
| CRASH_CONFIRMED | 충돌 긴급 해제 (EMERGENCY) | SWR-007 |
| INPUT_STALE | 갱신 지연으로 출력 유지 | SWR-013 |
| APPROACH_RISK_LOCK | 후측방 접근위험으로 잠금·해제 억제 | SWR-005 |
| OVERRIDE_REQUESTED | 억제 후 10초 이하 재입력을 override로 인정 | SWR-006 |
| SENSOR_FAULT | 센서 고장으로 출력 유지 | SWR-021 |
| CRASH_PENDING | 충돌 판정 대기로 LOCK 미적용 | SWR-008 |
| IGNITION_OFF | 시동 꺼짐 해제 | SWR-020 |
| FIRE_RELEASE / OVERTEMPERATURE_RELEASE | 화재·과온 강제 해제 | SWR-017 |
| ISOFIX_LOCK | ISOFIX 강제 잠금 | SWR-018 |
| AUTO_LOCK_SPEED | 차속 3 km/h 이상 자동 잠금 | SWR-003 |
| ADULT_PRESENT_RELEASE | 성인 탑승 강제 해제 | SWR-017 |
| DRIVER_LOCK / DRIVER_RELEASE | 운전자 명령 적용 | SWR-001, 002 |
| RELEASE_REJECTED_MOVING | 주행 중이라 운전자 해제 거절 | SWR-004 |
| RELEASE_REJECTED_ISOFIX | ISOFIX 연결로 운전자 해제 거절 | SWR-004 |
| COMMAND_REJECTED_STATE | state가 NORMAL이 아니라 운전자 명령 거절 | SWR-004 |
| INPUT_INVALID | 오류 필드·명령이 있고 출력을 바꾼 규칙은 없음 | SWR-013 |
| NO_CHANGE | 적용할 규칙이 없어 출력 유지 | SWR-019 |

## 4. 상태 결정표

state는 틱마다 아래 표를 위에서부터 차례로 검사해 처음 맞는 행으로 정한다. 상태 전이는 이 표의 결과가 틱 사이에 바뀌는 것이다.

| 순서 | 조건 | state |
|---|---|---|
| 1 | EMERGENCY 래치가 설정됨 (SWR-007) | EMERGENCY |
| 2 | 갱신 지연 (SWR-013) | DEGRADED |
| 3 | sensor_fault 유효값 = TRUE | FAULT |
| 4 | ignition_on 유효값 = FALSE | OFF |
| 5 | 그 외 | NORMAL |

- SW 시작 직후에는 ignition_on 초기 유효값이 FALSE이므로 state=OFF, 출력은 좌/우 RELEASE이다 (Q-13).
- 순서 유효 스냅샷으로 ignition_on=TRUE가 들어오면, 위 1~3행에 해당하지 않는 한 NORMAL이 된다.

## 5. 기능 요구사항

각 요구의 "검증"은 해당 요구를 검증할 테스트 수준이다: 단위(SWE.4) / 통합(SWE.5) / SIL(SWE.6 PC/SIL) / Web(SWE.6 Web 시뮬레이터).

### SWR-001 운전자 잠금 명령 처리
- **요구:** SW는 4개 경로(physical_button, avn, voice, mobile_app)로 받은 운전자 잠금 명령을 side(left/right/all)가 가리키는 도어에만 적용해야 한다.
- **수용 기준:** state=NORMAL이고 상위 순위 규칙이 걸리지 않을 때, 4개 경로 × 3개 side의 모든 조합에서 반영 주기에 선택된 출력만 LOCK이 된다. 선택되지 않은 출력은 바뀌지 않는다. 선택 도어의 reason은 DRIVER_LOCK이다.
- **상위:** OEM-FR-001 · **할당 ASIL:** QM · **검증:** 단위, SIL, Web

### SWR-002 운전자 해제 명령 처리
- **요구:** SW는 4개 경로로 받은 운전자 해제 명령을 SWR-004의 해제 허용 조건을 만족하는 도어에만 적용해야 한다.
- **수용 기준:**
  - 허용 조건을 만족하면 4개 경로 × 3개 side 조합에서 반영 주기에 선택된 출력만 RELEASE가 된다. 해당 도어의 reason은 DRIVER_RELEASE이다.
  - 만족하지 못한 도어는 출력이 유지되고, 거절 이유 코드가 남는다.
- **상위:** OEM-FR-001 · **할당 ASIL:** QM · **검증:** 단위, SIL, Web

### SWR-003 차속 자동 잠금
- **요구:** SW는 유효 차속이 3.0 km/h 이상이면 좌/우 차일드락을 잠가야 한다.
- **수용 기준:**
  - vehicle_speed_kph 유효값이 3.0 이상인 반영 주기부터 좌/우 출력이 LOCK이다. 이유 코드는 AUTO_LOCK_SPEED이다.
  - 2.9에서는 자동 잠금이 일어나지 않는다.
  - SWR-019의 상위 순위 규칙(1~8순위)이 걸린 도어는 그 규칙을 따른다.
- **상위:** OEM-FR-002 · **할당 ASIL:** QM · **검증:** 단위, SIL · **가정:** Q-04, Q-08

### SWR-004 운전자 해제 허용 조건
- **요구:** SW는 운전자 명령을 도어별로 다음 조건으로 판정해야 한다.
  1. state=NORMAL이 아니면 lock과 unlock 모두 거절한다.
  2. unlock은 유효 차속 < 3.0 km/h일 때만 허용한다.
  3. unlock은 대상 도어의 ISOFIX=FALSE일 때만 허용한다.
- **수용 기준:** 각 조건을 하나씩만 어긴 경우에, 해당 도어 출력이 유지되고 아래 이유 코드가 남는다. side=all이면 좌/우를 따로 판정하고, 한쪽만 거절되면 다른 쪽은 적용한다.

  | 어긴 조건 | 이유 코드 |
  |---|---|
  | 1 (state가 OFF, DEGRADED, FAULT, EMERGENCY 각각) | COMMAND_REJECTED_STATE |
  | 2 (차속 3.0 이상) | RELEASE_REJECTED_MOVING |
  | 3 (ISOFIX 연결) | RELEASE_REJECTED_ISOFIX |

  접근위험 도어에 대한 unlock은 SWR-005·006에서 처리한다(상위 순위).
- **상위:** OEM-FR-001 · **할당 ASIL:** QM · **검증:** 단위, SIL · **가정:** Q-09, Q-12

### SWR-005 후측방 접근위험 잠금 및 해제 억제
- **요구:** SW는 후측방 접근위험이 TRUE인 도어를 잠그고, 그 도어에 대한 해제 요청을 억제해야 한다.
- **수용 기준:**
  - rear_*_approach_risk 유효값이 TRUE인 반영 주기에 해당 출력이 LOCK이고, reason은 APPROACH_RISK_LOCK이다.
  - state가 FAULT여도 적용한다(Q-17).
  - 그 동안 해당 도어를 대상으로 하는 unlock(side가 그 도어 또는 all)이 와도 LOCK을 유지한다.
  - 접근위험이 TRUE가 된 뒤 처음 억제한 시각(now_s)을 도어별로 저장한다.
- **상위:** OEM-SR-002 · **할당 ASIL:** B · **검증:** 단위, SIL · **가정:** Q-01, Q-02, Q-17

### SWR-006 접근위험 경고 후 재입력 override
- **요구:** SW는 접근위험으로 해제가 억제된 도어에 같은 도어를 대상으로 하는 unlock이 10초 이하 안에 다시 들어오면 명시적 override 요청으로 인정해야 한다.
- **수용 기준:**
  - 처음 억제한 시각부터 경과 시간 ≤ 10.0 s인 재입력에서 override_*=TRUE가 되고, 해당 도어 reason은 OVERRIDE_REQUESTED이다. 10.0 s 정각은 인정한다.
  - 10.0 s를 넘긴 재입력은 새 첫 요청으로 다시 억제하고, 억제 시각을 그 시각으로 갱신한다.
  - 접근위험이 TRUE인 동안 출력은 LOCK을 유지한다(Q-01).
  - 해당 도어의 접근위험이 FALSE가 되는 반영 주기에 override_*와 억제 시각을 지운다. 그 뒤 해제하려면 운전자가 다시 unlock해야 한다(SWR-002).
  - state가 OFF가 되면 override_*를 지운다.
- **상위:** OEM-SR-002, OEM-FR-003 · **할당 ASIL:** B · **검증:** 단위, SIL, Web · **가정:** Q-01, Q-15

### SWR-007 충돌 긴급 해제
- **요구:** SW는 crash_status 유효값이 CONFIRMED가 되면 다른 모든 규칙보다 우선해 좌/우 차일드락을 해제하고, 해제 조건이 될 때까지 해제를 유지(래치)해야 한다.
- **수용 기준:**
  - CONFIRMED의 반영 주기에 좌/우 출력이 RELEASE이고 state=EMERGENCY, reason은 CRASH_CONFIRMED이다. 이때 지연은 0 ms로, 300 ms 예산을 만족한다.
  - 같은 VehicleSnapshot의 다른 필드에 오류가 있거나, 운전자 명령이 잘못되거나, 순서 무효 스냅샷이거나, DEGRADED 중이어도 마찬가지다(SWR-013, Q-19, Q-21).
  - 래치 동안에는 crash_status가 NONE으로 바뀌어도, 운전자 LOCK·접근위험·ISOFIX·센서 고장·갱신 지연이 와도 RELEASE와 EMERGENCY를 유지한다.
  - **래치 해제:** ignition_on 유효값이 FALSE로 **1.0 s 이상 연속** 유지되고 crash_status 유효값이 CONFIRMED가 아니면, 그 틱에 래치를 지운다. 그 틱부터는 4장 상태 결정표에 따라 OFF가 된다. 0.99 s에서는 아직 래치 상태다.
  - 1.0 s는 ignition_on과 crash_status 필드가 모두 최신(필드 갱신 후 경과 ≤ 0.200 s)인 틱만 연속으로 센다. 어느 한쪽이 최신이 아닌 틱이 끼면 0부터 다시 센다. 오래된 FALSE 값으로 래치가 풀리지 않게 하기 위해서다.
- **상위:** OEM-SR-001 · **할당 ASIL:** B · **검증:** 단위, SIL · **가정:** Q-05, Q-06

### SWR-008 충돌 판정 대기(PENDING) 처리
- **요구:** SW는 crash_status 유효값이 PENDING인 동안 QM 규칙이 만드는 새 LOCK을 적용하지 않아야 한다. 탈출을 막을 수 있는 동작을 억제하기 위해서다.
- **수용 기준:**
  - PENDING인 틱에 ISOFIX 잠금, 자동 잠금, 운전자 LOCK 명령이 와도 해당 도어 출력은 직전 값을 유지하고, reason은 CRASH_PENDING이다.
  - 접근위험 잠금(SWR-005, ASIL B)은 PENDING 중에도 적용한다.
  - 강제 해제(SWR-017), IGN OFF 해제(SWR-020), 운전자 해제는 PENDING 중에도 적용한다.
  - PENDING에서 CONFIRMED로 바뀌면 SWR-007을 적용한다.
  - PENDING의 지속 시간에는 상한을 두지 않는다(Q-07).
- **상위:** OEM-SR-001 · **할당 ASIL:** B · **검증:** 단위, SIL · **가정:** Q-07

### SWR-009 좌/우 독립 판정
- **요구:** SW는 도어별 입력(접근위험, ISOFIX, override)을 해당 도어의 출력과 reason에만 반영해야 한다.
- **수용 기준:** 왼쪽에만 접근위험·ISOFIX·override를 넣은 경우와 오른쪽에만 넣은 경우 각각에서, 반대쪽의 출력, override, reason은 그 입력이 없을 때와 같다.
- **상위:** OEM-SR-002 · **할당 ASIL:** B · **검증:** 단위, SIL

### SWR-013 입력 유효성 및 갱신 지연 처리
- **요구:** SW는 판정 전에 필드마다 형식과 범위를 검사해 오류 필드를 판정에 쓰지 않아야 한다. 또 판정 필드의 갱신이 끊기면 DEGRADED 상태로 바꿔야 한다.
- **수용 기준:**
  - **필드 단위 대체:** 순서 유효 스냅샷에서 3.1절 규칙을 어긴 필드는 그 필드의 직전 유효값으로 대체해 판정한다. 그 틱의 input_validity는 INVALID이다. 오류가 없는 다른 필드는 그대로 판정에 쓴다.
    - 예: vehicle_speed_kph=301과 crash_status=CONFIRMED가 함께 오면 SWR-007을 적용한다.
  - **명령 오류:** 잘못된 DriverCommand는 그 명령만 거절하고, input_validity는 INVALID이다(3.2절).
  - **순서 무효 스냅샷:** 차량 필드와 운전자 명령을 판정에 쓰지 않고, 필드 갱신 시각도 갱신하지 않는다. input_validity는 INVALID이다.
    - 예외: crash_status 필드가 유효한 CONFIRMED이면 SWR-007을 적용한다(Q-21).
    - 예: 새 프레임의 approach_risk=TRUE 다음에 옛 timestamp의 FALSE 프레임이 와도, 접근위험 TRUE를 유지한다.
  - **갱신 지연:** 판정 필드 중 하나라도 now_s − 필드 갱신 시각 > 0.200 s가 된 첫 틱에 state=DEGRADED, input_validity=STALE이 된다.
    - 이 틱은 200 ms를 넘긴 뒤 100 ms 안에 온다(10 ms 틱이면 최대 10 ms). 정확히 0.200 s는 아직 정상이다.
    - 입력이 끊긴 경우, 특정 필드만 계속 오류인 경우, 순서 무효 스냅샷만 계속 오는 경우 모두 이 규칙으로 잡힌다.
    - SW 시작 후 순서 유효 스냅샷이 한 번도 없어도 같은 규칙을 적용한다.
  - **DEGRADED 중:** 직전 확정 출력을 유지하고(reason=INPUT_STALE), 운전자 명령은 거절한다. EMERGENCY 래치와 유효한 crash_status=CONFIRMED는 예외다(SWR-019 1순위).
  - **복귀:** 모든 판정 필드의 경과 시간이 0.200 s 이하가 된 틱에 DEGRADED를 벗어나고, 4장 상태 결정표에 따른 state가 된다.
- **상위:** OEM-SR-003 · **할당 ASIL:** B · **검증:** 단위, SIL · **가정:** Q-08~Q-11

### SWR-017 화재·과온·성인 탑승 강제 해제
- **요구:** SW는 fire_detected, overtemperature_detected, adult_present 유효값 중 하나라도 TRUE이면 좌/우 차일드락을 해제해야 한다. 우선순위는 SWR-019를 따른다.
- **수용 기준:**
  - 각 입력을 단독으로 TRUE로 넣으면, 반영 주기에 좌/우 출력이 RELEASE이다. 도어 reason은 각각 FIRE_RELEASE, OVERTEMPERATURE_RELEASE, ADULT_PRESENT_RELEASE이다.
  - 여러 입력이 동시에 TRUE이면 FIRE_RELEASE > OVERTEMPERATURE_RELEASE > ADULT_PRESENT_RELEASE 순으로 이유 코드를 고른다.
  - **상태형 규칙:** 입력이 TRUE인 동안 매 틱 적용한다. 입력이 FALSE가 된 뒤에는 출력을 되돌리지 않고 유지한다(그 뒤 다른 규칙이 없으면 NO_CHANGE).
  - 화재·과온은 ISOFIX 잠금과 자동 잠금보다 우선한다. 성인 탑승은 ISOFIX 도어와 차속 3.0 km/h 이상에서는 해제하지 않는다(Q-03, Q-04).
- **상위:** OEM-FR-005 · **할당 ASIL:** QM · **검증:** 단위, SIL, Web · **가정:** Q-02~Q-04, Q-18

### SWR-018 ISOFIX 강제 잠금
- **요구:** SW는 ISOFIX가 연결된 도어의 차일드락을 잠가야 한다.
- **수용 기준:**
  - isofix_left 유효값만 TRUE이면 반영 주기에 lock_left=LOCK(reason=ISOFIX_LOCK)이고, lock_right는 직전 값을 유지한다. 오른쪽도 대칭이다.
  - **상태형 규칙:** 입력이 TRUE인 동안 매 틱 적용한다. FALSE가 된 뒤에는 출력을 유지한다.
  - 화재·과온 강제 해제가 동시에 걸리면 해제를 따른다(Q-03).
- **상위:** OEM-FR-006 · **할당 ASIL:** QM · **검증:** 단위, SIL, Web · **가정:** Q-03

### SWR-019 판정 우선순위 중재
- **요구:** SW는 한 틱에 여러 규칙이 동시에 걸리면 아래 순위에 따라 도어별 출력을 결정해야 한다. 도어마다 그 도어에 걸린 규칙 중 순위가 가장 높은 규칙이 출력과 reason을 정한다.
- **우선순위표:**

  | 순위 | 규칙 | 결과 | 할당 ASIL |
  |---|---|---|---|
  | 1 | 충돌 CONFIRMED 또는 EMERGENCY 래치 (SWR-007) | 좌/우 RELEASE | B |
  | 2 | 갱신 지연 (SWR-013) | 좌/우 출력 유지 | B |
  | 3 | 도어별 접근위험 (SWR-005, 006) | 해당 도어 LOCK | B |
  | 4 | sensor_fault=TRUE (SWR-021) | 3순위가 아닌 도어의 출력 유지 | B |
  | 5 | 충돌 PENDING (SWR-008) | 6~11순위가 LOCK을 만드는 도어는 출력 유지. RELEASE를 만드는 도어는 그대로 적용 | B |
  | 6 | ignition_on=FALSE (SWR-020) | 좌/우 RELEASE | QM |
  | 7 | 화재·과온 (SWR-017) | 좌/우 RELEASE | QM |
  | 8 | 도어별 ISOFIX (SWR-018) | 해당 도어 LOCK | QM |
  | 9 | 차속 ≥ 3.0 km/h (SWR-003) | 좌/우 LOCK | QM |
  | 10 | 성인 탑승 (SWR-017) | 좌/우 RELEASE | QM |
  | 11 | 운전자 명령 (SWR-001, 002, 004) | 선택 도어 LOCK·RELEASE 또는 거절 | QM |
  | 12 | 없음 | 출력 유지 (INPUT_INVALID 또는 NO_CHANGE) | — |

- **배치 원칙:** 할당 ASIL B 규칙(1~5순위)은 QM 규칙(6~11순위)보다 항상 위에 있다. QM 로직이 ASIL B 요구의 동작을 뒤집지 못하게 하기 위해서다 (QA-ECL-001 원칙 1).
- **수용 기준:**
  - 1~11순위 규칙에서 두 규칙을 동시에 거는 모든 쌍(55쌍)에서, 각 도어의 출력과 reason이 순위가 높은 규칙의 결과와 같다.
  - 예외 규칙은 해당 쌍에서 예외대로 동작한다: 5순위는 LOCK만 무효화하고, 4순위는 3순위 도어를 제외한다.
  - 5순위 예외는 세 규칙 조합으로도 검증한다: PENDING + 8순위 ISOFIX(LOCK) + 7순위 화재(RELEASE)와 PENDING + 9순위 차속(LOCK) + 11순위 운전자 해제.
  - priority_reason과 reason_code는 3.3절 규칙에 따른다.
- **상위:** OEM-SR-001, SR-002, SR-003, SR-004, FR-001, FR-002, FR-003, FR-005, FR-006, FR-007 (파생) · **할당 ASIL:** B · **검증:** 단위, SIL · **가정:** Q-01~Q-07, Q-14, Q-16~Q-18

### SWR-020 시동 꺼짐 해제
- **요구:** SW는 ignition_on 유효값이 FALSE이면 좌/우 차일드락을 초기 해제 상태로 돌려야 한다.
- **수용 기준:**
  - SWR-019의 1~5순위 규칙이 걸리지 않은 도어는, ignition_on=FALSE의 반영 주기에 RELEASE이다. reason은 IGNITION_OFF이다.
  - state는 4장 상태 결정표에 따른다(EMERGENCY, DEGRADED, FAULT가 아니면 OFF).
  - state가 OFF가 되면 override를 지운다(SWR-006).
  - EMERGENCY 래치는 SWR-007의 해제 조건으로만 지운다.
  - 시스템 시작 시 초기 상태도 RELEASE/OFF이다.
- **상위:** OEM-FR-007 · **할당 ASIL:** QM · **검증:** 단위, SIL, Web · **가정:** Q-06, Q-13, Q-16

### SWR-021 센서 고장 시 출력 유지
- **요구:** SW는 sensor_fault 유효값이 TRUE이면 새 명령을 적용하지 않고 직전 확정 출력을 유지해야 한다.
- **수용 기준:**
  - sensor_fault=TRUE의 반영 주기에 좌/우 출력이 직전 값과 같고, state=FAULT, warning_code=SENSOR_FAULT, reason=SENSOR_FAULT이다.
  - state가 EMERGENCY나 DEGRADED여서 FAULT가 아니어도, sensor_fault 유효값이 TRUE이면 warning_code=SENSOR_FAULT이다.
  - 그 동안 운전자 명령, 자동 잠금, 강제 해제·잠금, IGN OFF 해제가 출력을 바꾸지 않는다.
  - 예외는 두 가지다: 충돌 CONFIRMED(1순위)와 접근위험 도어 LOCK(3순위)(Q-17).
  - sensor_fault=FALSE인 반영 주기에 4장 상태 결정표에 따른 state로 돌아온다.
- **상위:** OEM-SR-004 · **할당 ASIL:** B · **검증:** 단위, SIL · **가정:** Q-05, Q-10, Q-17, Q-18

## 6. 표시·기록 요구사항

### SWR-010 결정 기록 생성과 식별자
- **요구:** SW는 다음 두 경우에 결정 기록을 하나 만들고, 고유하고 단조 증가하는 event_id를 붙여야 한다.
  1. VehicleSnapshot을 처리한 틱. 오류 필드가 있는 입력도 포함한다.
  2. 입력이 없는 틱이지만 출력이나 state가 바뀐 틱 (예: DEGRADED 전이)
- **수용 기준:**
  - VehicleSnapshot N건을 처리하면 기록이 N건 생긴다.
  - 입력 없이 DEGRADED로 바뀐 틱에도 1건이 생기고, 입력 없이 아무것도 바뀌지 않은 틱에는 생기지 않는다.
  - event_id는 1부터 1씩 증가하고, 프로세스를 재시작하면 1부터 다시 시작한다.
- **상위:** OEM-NFR-002 · **할당 ASIL:** QM · **검증:** 단위

### SWR-011 결정 기록 스키마
- **요구:** SW는 결정 기록에 허용된 필드만 저장해야 한다.
- **수용 기준:**
  - 기록의 필드 집합은 {event_id, now_s, state, lock_left, lock_right, override_left, override_right, input_validity, reason_left, reason_right, priority_reason, warning_code}와 정확히 같다.
  - 영상, 음성, 개인 식별자, 운전자 명령 source, 원본 입력 값은 저장하지 않는다.
- **상위:** OEM-NFR-002 · **할당 ASIL:** QM · **검증:** 단위, 통합

### SWR-012 결정 기록 보존과 휘발성
- **요구:** SW는 최근 결정 기록 100건을 메모리에만 보존해야 한다.
- **수용 기준:**
  - 입력 없이 출력이나 state가 바뀌는 틱이 없게 VehicleSnapshot 101건을 연속 처리한 뒤 조회하면, event_id 2~101의 100건이 순서대로 나온다.
  - 파일, DB 등 프로세스 밖에 저장하지 않는다. 프로세스를 재시작한 뒤 조회하면 0건이다.
- **상위:** OEM-NFR-002 · **할당 ASIL:** QM · **검증:** 단위, 통합

### SWR-014 상태 조회
- **요구:** SW는 현재 출력, 상태, 입력 유효성, 최근 결정 이유를 조회하는 기능을 제공해야 한다.
- **수용 기준:** 상태 조회 결과에 3.3절의 모든 출력 필드가 있고, 마지막 틱의 출력과 값이 같다.
- **상위:** OEM-FR-004 · **할당 ASIL:** QM · **검증:** 단위, 통합

### SWR-015 Web 표시 인터페이스
- **요구:** SW는 HTTP로 시험 입력을 받아 틱을 진행하고, 상태와 결정 기록을 JSON으로 제공해야 한다.
- **수용 기준:**

  | 요청 | 동작 | 응답 |
  |---|---|---|
  | `POST /api/tick` 본문 `{"now_s": 수, "snapshot": 객체 또는 null}` | 한 틱을 판정한다 | 200, 3.3절 출력 JSON |
  | `GET /api/status` | 상태를 조회한다 (SWR-014) | 200, 3.3절 출력 JSON |
  | `GET /api/events` | 기록을 조회한다 (SWR-012) | 200, 기록 배열 JSON (event_id 오름차순) |
  | 본문이 JSON이 아니거나 now_s가 없음·비유한수·직전 now_s 이하 | 틱을 진행하지 않는다 | 400 |
  | snapshot 안의 필드 오류 | SWR-013대로 처리한다 | 200 (input_validity=INVALID) |
  | 응답 직렬화 실패 | — | 500 |

  priority_reason과 reason_code 값은 3.4절 이유 코드 중 하나다.
- **상위:** OEM-FR-004 · **할당 ASIL:** QM · **검증:** 통합, Web

## 7. 비기능 요구사항

### SWR-016 결정론적 재생
- **요구:** SW는 같은 초기 상태, 같은 now_s 순서(고정 시계), 같은 입력 순서에 대해 항상 같은 출력을 만들어야 한다. 실제 시각, 난수, 스레드 순서에 영향을 받지 않아야 한다.
- **수용 기준:** 고정 시계로 만든 입력 벡터를 새 인스턴스에서 1,000회 재생했을 때, **모든 틱의 3.3절 출력 전체**를 순서대로 직렬화한 해시가 모두 같다.
- **상위:** OEM-NFR-001 · **할당 ASIL:** QM · **검증:** SIL

## 8. 요구 ID 대응 요약

| 범위 | SWR |
|---|---|
| 기능 (5장) | 001, 002, 003, 004, 005, 006, 007, 008, 009, 013, 017, 018, 019, 020, 021 |
| 표시·기록 (6장) | 010, 011, 012, 014, 015 |
| 비기능 (7장) | 016 |

모두 21건이며 결번은 없다. SWR-019는 공급자가 할당한 파생 요구다(Q-14).
