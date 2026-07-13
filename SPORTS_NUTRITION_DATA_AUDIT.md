# 스포츠영양 식단 데이터 감사 및 반영 결과

## 판단

기존 60개 데이터는 단백질·탄수화물·채소/과일 구성은 구조화되어 있었지만,
운동 전후 맥락, 명시적 알레르겐, 미량영양소 역할, 근거 출처가 없어
영양적으로 검증된 데이터라고 부르기에는 부족했다.

이번 변경은 근거 없는 수치를 만들지 않고 다음 원칙을 적용했다.

- 메뉴별 표준 중량과 조리 상태가 없으므로 `nutrition_verified=false` 유지
- ACSM·ISSN의 운동 연료·회복·단백질 분배 원칙을 정성 태그로 저장
- USDA MyPlate의 식품군·통곡물·다양한 단백질원 원칙 반영
- AIS 스포츠영양사 레시피의 실제 음식 조합 패턴 반영
- 영양 수치 검증은 향후 USDA FoodData Central 식품 코드와 표준 중량이 확보된 뒤 수행

## 주요 근거

- Academy/DC/ACSM, Nutrition and Athletic Performance:
  https://pubmed.ncbi.nlm.nih.gov/26891166/
- ISSN, Protein and Exercise:
  https://jissn.biomedcentral.com/articles/10.1186/s12970-017-0177-8
- ISSN, Nutrient Timing:
  https://jissn.biomedcentral.com/articles/10.1186/s12970-017-0189-4
- USDA MyPlate:
  https://www.myplate.gov/eat-healthy/what-is-myplate
- USDA FoodData Central Foundation Foods:
  https://fdc.nal.usda.gov/Foundation_Foods_Documentation/
- Australian Institute of Sport Recipes:
  https://www.ais.gov.au/nutrition/recipes
- AIS Pasta with Chicken and Corn:
  https://www.ais.gov.au/nutrition/recipes/pasta_with_chicken_and_corn
- AIS Any Fruit Smoothie:
  https://www.ais.gov.au/nutrition/recipes/any_fruit_smoothie
- AIS Mango Smoothie:
  https://www.ais.gov.au/nutrition/recipes/mango_smoothie
- AIS Lachie's Rogan Josh with Spinach and Potatoes:
  https://www.ais.gov.au/nutrition/recipes/lachies_rogan_josh_with_spinach_and_potatoes

## DB 반영

`meal_options`에 다음 필드를 추가했다.

- `allergens`
- `dietary_patterns`
- `protein_families`
- `whole_grain`
- `micronutrient_focus`
- `training_contexts`
- `digestibility`
- `recovery_roles`
- `evidence_source_ids`
- `nutrition_verified`
- `review_status`
- `catalog_revision`

`nutrition_evidence_sources` 테이블에 조직, 문서명, URL, 근거 유형과 적용 범위를 저장한다.

## 운동 식단 패턴 추가

AIS 공식 레시피와 스포츠영양 원칙을 참고해 다음 계열을 추가했다.

- 바나나·베리·요거트·오트밀
- 달걀·루콜라 통곡물 샌드위치
- 두부 채소 쌀국수
- 닭고기·옥수수 통밀 파스타
- 소고기 채소 덮밥
- 참치 토마토 통밀 파스타
- 두부 채소 커리와 쌀
- 양고기·시금치·감자 커리
- 닭고기·망고·채소 쌀볼
- 우유·요거트·과일 스무디

메뉴를 그대로 복제한 것이 아니라 식품 조합 패턴을 한국어 정성 식단으로 변환했다.

## 현재 다양성

- 총 72개: 아침·점심·저녁·간식 각각 18개
- 단백질 family 태그: 콩류 16, 대두 14, 가금류 11, 생선 11,
  유제품 10, 붉은살코기 10, 달걀 9, 기타 해산물 5
- 식단 패턴: 비건 호환 19, 채식 호환 16, 페스코 호환 16, 일반식 21
- 통곡물 기반 54
- 오메가3 식품원 11, 칼슘 관련 식품 28, 철분 관련 식품 47
- 운동 전 후보 5, 운동 후 혼합식 후보 72, 휴대 간식 18

태그는 서로 중복될 수 있으며, 영양소 수치를 의미하지 않는다.

## 안전성과 한계

- 대두·밀·참깨·메밀·우유·달걀·생선·갑각류·연체류·견과류 알레르겐을
  DB 태그로 hard exclusion한다.
- 조미료나 브랜드 제품에 숨은 알레르겐은 레시피가 확정되기 전까지 완전히 보장할 수 없다.
- 모든 메뉴는 `principle_based_unverified_portion` 상태다.
- 향후 영양값 검증에는 식재료별 표준 중량, 조리 상태, FDC ID와 영양 계산 스냅샷이 필요하다.

## 검증

- 로컬 전체: `192 passed, 33 subtests passed`
- Docker 식단 DB migration: `meal_0002`
- 식단 후보 72개, 근거 출처 10개, revision 2 적용 72개
- 기존 사용자 DB 행 수 변화 없음
- Docker MCP 8회 호출에서 8개 서로 다른 계획
- Docker 카탈로그·알레르기·DB 격리 테스트 22개 통과
