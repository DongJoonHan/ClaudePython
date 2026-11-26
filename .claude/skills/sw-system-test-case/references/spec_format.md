# 명세 JSON 형식 (build_workbook.py 입력)

```json
{
  "project": "BCM 도어 잠금 SW",
  "basis_document": "SRS_DoorLock_v1.3.docx",
  "basis": [
    {"id": "SWR-001", "title": "차속 15 km/h 이상 시 자동 잠금", "type": "기능", "asil": "B"},
    {"id": "SWR-010", "title": "잠금 명령 응답 200 ms 이내", "type": "비기능", "asil": "QM"},
    {"id": "SWR-020", "title": "코드 MISRA 준수", "type": "비기능",
     "not_testable_reason": "정적 분석 대상 - 시스템 테스트로 검증 불가, SWE.4 정적 검증 권고"}
  ],
  "test_cases": [
    {
      "id": "STC-F-001",
      "category": "기능",
      "basis_ids": ["SWR-001"],
      "purpose": "자동 잠금 임계값 직전(14.9 km/h)에서 잠기지 않음을 확인",
      "preconditions": ["IGN ON", "모든 도어 닫힘, 잠금 해제 상태"],
      "environment": "HIL",
      "inputs": {"VehicleSpeed": "14.9 km/h (5 s 유지)"},
      "procedure": ["차속을 0에서 14.9 km/h까지 1 km/h/s로 올린다", "5 s 유지한다", "DoorLockStatus를 관측한다"],
      "expected": "DoorLockStatus = UNLOCKED 유지, 잠금 액추에이터 출력 없음",
      "techniques": ["경계값 분석"],
      "proposed": false
    },
    {
      "id": "STC-F-014",
      "category": "기능",
      "basis_ids": ["SWR-001", "SWR-003"],
      "purpose": "PICT 조합 #3: CRANK 중 R단, 도어 열림 조건의 잠금 판정",
      "inputs": {"전원모드": "CRANK", "기어": "R", "도어": "열림", "차속_kph": "3"},
      "procedure": ["..."],
      "expected": "...",
      "techniques": ["페어와이즈(PICT)"],
      "pict_model": "PW-01"
    }
  ],
  "pict_models": [
    {"id": "PW-01", "basis_ids": ["SWR-001", "SWR-003"], "command": "pict model_PW-01.txt /o:2",
     "model_text": "<모델 파일 전문>", "rows": ["<run_pict.py 출력의 rows 그대로>"], "notes": ""}
  ],
  "assumptions": [
    {"id": "Q-01", "type": "질의", "related_basis": ["SWR-001"],
     "content": "차속 신호 분해능 미기재 - 0.1 km/h로 가정", "impact": "STC-F-001~004 경계값"}
  ],
  "template": {"sheet": "TC", "header_row": 3,
               "columns": {"id": "TC No.", "basis_ids": "Req. ID", "purpose": "Objective",
                           "inputs": "Input", "procedure": "Steps", "expected": "Expected Result",
                           "techniques": "Method", "kind": "비고"}}
}
```

## 필드 규칙

**basis[]**
- `id`, `title`, `type`(`기능`/`비기능`)은 필수이고, `asil`은 선택입니다.
- 시스템 테스트로 검증할 수 없는 항목에는 `not_testable_reason`을 적고, 사용자에게도 반드시 알립니다. 이런 항목은 커버리지에서 미커버로 집계되고 스크립트가 오류를 냅니다. 커버리지 100%를 거짓으로 보고하지 않기 위해서입니다. 사용자가 제외를 승인했을 때만 `--allow-gaps`로 출력합니다.
- `ep_bva_na_reason`: 경계값/동치 기법을 적용할 입력 범위가 없는 항목(예: 단일 이벤트 응답)에 사유를 적습니다.

**test_cases[]**
- `id`, `category`, `basis_ids`, `purpose`, `inputs`, `procedure`, `expected`, `techniques`가 필수입니다.
- `preconditions`, `environment`, `proposed`, `pict_model`은 선택입니다.
- 값은 문자열, 리스트, 딕셔너리 모두 쓸 수 있습니다. `procedure` 리스트는 번호가 붙은 줄로 출력되고, `inputs` 딕셔너리는 `키 = 값` 줄로 출력됩니다.
- `proposed: true`이면 "구분" 열에 **제안**이 표시되고 행이 노란색으로 칠해집니다.
- 페어와이즈 TC는 `pict_model`이 필수입니다.

**template** (선택): 고객 양식 .xlsx를 `--template`으로 넘길 때만 씁니다.
- `columns`는 필드 키를 양식의 헤더 텍스트에 연결합니다(정확히 일치해야 함).
- 양식에 필수 항목(ID, 베이시스 ID, 목적, 입력, 절차, 예상 출력, 기법, 구분) 열이 없으면, 스크립트가 마지막 열에 추가하고 경고를 냅니다. 제안 표시를 넣을 열이 없으면 `kind`를 비고 열 같은 곳에 연결하세요.
- `sheet`는 TC 행 양식이 있는 시트입니다. 기능과 비기능 시트는 이 시트를 복사해 만들고, 이름은 `sheet_functional`과 `sheet_nonfunctional`로 바꿀 수 있습니다.
- `header_row`를 생략하면 헤더 텍스트가 가장 많이 일치하는 행을 자동으로 찾습니다.

## 출력 시트

| 시트 | 내용 |
|---|---|
| 기능 테스트 / 비기능 테스트 | TC 목록 (제안 행은 노란색) |
| 추적성 매트릭스 | 베이시스 항목별 TC 수, TC ID, 적용 기법, 커버 상태 (미커버 행은 주황색) |
| 커버리지 요약 | 베이시스 커버리지 %, 역추적률, 기능/비기능 및 기본/제안 개수, 기법별 사용 횟수 |
| 가정 및 질의 | `assumptions`가 있을 때만 생성 |
| 페어와이즈 모델 | `pict_models`가 있을 때만 생성 (재현용 모델 전문과 명령) |
