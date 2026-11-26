# SW 요구사항 명세서 — 레인 센싱 와이퍼 제어 (v2.1)

## 입력
- WiperSwitch: OFF, AUTO, LOW, HIGH, MIST (10 ms)
- RainIntensity: 0 ~ 100 % (1 % 단위, 레인센서 LIN, 50 ms 주기, 255 = 센서 오류)
- VehicleSpeed: 0 ~ 255 km/h (0.1 km/h, CAN 20 ms)
- AutoSensitivity: 1 ~ 5 (사용자 설정, 기본값 3)
- IgnitionState: OFF, ACC, ON

## 출력
- WiperMotorCmd: STOP, INT, LOW, HIGH
- IntervalTime_ms: INT 동작 시 와이핑 간 대기 시간

## 요구사항
- **RW-001** WiperSwitch = LOW / HIGH 이면 RainIntensity 와 무관하게 WiperMotorCmd 를 각각 LOW / HIGH 로 출력한다.
- **RW-002** WiperSwitch = MIST 이면 스위치가 유지되는 동안 LOW 로 동작하고, 해제 시 현재 와이핑 사이클 완료 후 STOP 한다.
- **RW-003** WiperSwitch = AUTO 일 때 WiperMotorCmd 는 유효 강우량 E = RainIntensity × (AutoSensitivity / 3) 에 따라 다음과 같이 결정한다: E < 10 → STOP, 10 ≤ E < 40 → INT, 40 ≤ E < 70 → LOW, E ≥ 70 → HIGH.
- **RW-004** INT 동작 시 IntervalTime_ms = 6000 − 150 × E (단, 최소 1000 ms).
- **RW-005** AUTO 모드에서 VehicleSpeed < 5.0 km/h 이면 결정된 단계를 한 단계 낮춘다 (HIGH→LOW, LOW→INT, INT 유지).
- **RW-006** RainIntensity = 255 (센서 오류) 또는 500 ms 이상 미수신 시, AUTO 모드는 INT(IntervalTime_ms = 4000) 로 고정 동작한다.
- **RW-007** IgnitionState 가 ON 이 아니면 WiperMotorCmd = STOP 이며, 동작 중 IGN OFF 시 와이퍼는 파킹 위치까지 이동 후 정지한다.
- **RW-008** (비기능) WiperSwitch 변경 후 WiperMotorCmd 반영은 100 ms 이내여야 한다.
- **RW-009** (비기능) 레인센서 미수신 판정 시간 오차는 ±50 ms 이내여야 한다.
