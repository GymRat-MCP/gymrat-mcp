# Persona Quality Fix 결과

실행일: 2026-07-12
브랜치: `fix/persona-quality`
기준 커밋: `d77793c`

## 수정한 문제

### 안전한 식단 계획

- 정확한 kcal·칼로리 제한 제거
- 정확한 g·그램 제한 제거
- 굶기·금식·끼니 거르기 조건 제거
- 음식 선호·비선호·알레르기 같은 안전한 취향은 유지
- 제거된 조건의 종류를 구조화 필드로 반환
- 최종 `assistant_message`에서 해당 조건을 반영하지 않았다고 명시

### 문맥에 맞는 페르소나

- 모든 응답에 붙던 범용 상투구를 제거
- 회복·부상·오류·확인 질문·기록 완료·식단 계획 문맥을 구분
- 회복 권고 뒤의 `힘들면 그게 크는 신호` 제거
- 부상 경고 뒤의 `계획대로 가자` 제거
- 식단 확인 질문 뒤의 압박 문구 제거
- 페르소나별 lead-in과 종결어미를 본문에 적용
- 이미 렌더링된 문장 중복 가공 방지

### 반복 완화

- 아침·점심·저녁 가이드마다 반복되던 페르소나 라벨 제거
- 식단 계획 전체에서 top-level 사용자 문장에만 페르소나 라벨 적용
- 네 후보 중 하나를 매번 붙이던 범용 suffix 로테이션 제거

### Override 처리

- `devil`, `angel`, `coach`, `realist` 영문 별칭 지원
- 앞뒤 공백 제거 후 정상값 판정
- 잘못된 override는 저장된 프로필 페르소나를 유지
- `persona_source`와 `persona_override_status`를 실제 처리 결과대로 반환
- `generate_meal_plan`, `suggest_meal_adjustment`에도 요청 한정 `persona_override` 추가

### Body 응답 계약

- `log_weight`에 `persona`, `assistant_message`, `display_text`, `message`, `base_message`, `user_response_contract` 추가
- 체중과 인바디 기록 UX를 동일한 계약으로 통일

## 검증 결과

### 전체 로컬 테스트

```text
192 passed, 33 subtests passed
```

### Docker persona 회귀 테스트

```text
Ran 40 tests
OK
```

### 실제 Docker MCP 인수 테스트

Endpoint: `http://127.0.0.1:8000/mcp`

| 항목 | 결과 |
| --- | --- |
| 네 페르소나 회복 문장 구분 | PASS |
| 회복 문맥의 밀어붙이기 문구 제거 | PASS |
| 부상 경고의 운동 강행 문구 제거 | PASS |
| 위험 식단 조건 제거 | PASS |
| 위험 조건 미반영 안내 | PASS |
| 안전한 음식 취향 보존 | PASS |
| `devil` 영문 override | PASS |
| 잘못된 override에서 프로필 유지 | PASS |
| 요청 한정 식단 persona | PASS |
| 체중 기록 persona 응답 계약 | PASS |
| 끼니별 라벨 반복 제거 | PASS |

회복 필요 상황의 실제 응답:

- 악마: `지금은 무리하지 않는 게 우선입니다.`
- 천사: `몸을 먼저 돌봐도 괜찮아요.`
- 현실파이터: `지금은 회복을 우선순위로 둡시다.`
- 코치: `좋은 훈련은 회복까지 포함합니다.`

## 남은 의도적 동작

- 같은 입력은 같은 결과를 반환한다. 결정론은 유지하지만 반복 상투구 자체는 제거했다.
- 식단 확인 도중 프로필 페르소나를 바꾸면 최종 확정 응답은 최신 프로필 페르소나를 사용한다.
- top-level 사용자 문장에는 현재 모드를 식별할 수 있도록 페르소나 라벨을 한 번 유지한다.

## 실행 상태

- Docker PostgreSQL과 MCP 서버는 최신 fix 브랜치 이미지로 실행 중이다.
- 제품 코드, 테스트, 감사·검증 문서를 하나의 변경 묶음으로 관리한다.
