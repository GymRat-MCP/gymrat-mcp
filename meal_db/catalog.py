"""Seed catalog for the isolated meal database.

The catalog intentionally contains qualitative plate compositions only.  It is
safe to import from migration/seed code and has no dependency on the product
database or ORM models.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable


MEAL_TYPES = ("아침", "점심", "저녁", "간식")
GOALS = ("증량", "감량", "유지")

_ANIMAL_MEAT = {"닭고기", "칠면조", "소고기", "돼지고기", "양고기"}
_FISH = {"연어", "고등어", "참치", "흰살생선"}
_SEAFOOD = _FISH | {"새우", "오징어", "문어"}
_SOY = {"두부", "연두부", "대두", "템페", "에다마메", "된장"}
_LEGUMES = _SOY | {"콩", "검은콩", "병아리콩", "렌틸콩", "흰콩", "강낭콩"}
_DAIRY = {"우유", "요거트", "그릭요거트", "코티지치즈", "치즈"}
_WHOLE_GRAINS = {"현미", "현미밥", "잡곡밥", "보리", "보리밥", "오트밀", "퀴노아", "통곡물", "통밀빵", "통밀 또띠아", "통밀 파스타", "호밀빵"}


def _ingredient_matches(ingredients: set[str], terms: set[str]) -> bool:
    return any(term in ingredient for ingredient in ingredients for term in terms)


def _derive_allergens(ingredients: set[str]) -> list[str]:
    allergens = set()
    if _ingredient_matches(ingredients, {"달걀"}): allergens.add("egg")
    if _ingredient_matches(ingredients, _DAIRY): allergens.add("milk")
    if _ingredient_matches(ingredients, _FISH): allergens.add("fish")
    if _ingredient_matches(ingredients, {"새우"}): allergens.add("crustacean")
    if _ingredient_matches(ingredients, {"오징어", "문어"}): allergens.add("mollusk")
    if _ingredient_matches(ingredients, {"땅콩", "땅콩버터"}): allergens.add("peanut")
    if _ingredient_matches(ingredients, {"호두", "아몬드", "캐슈너트"}): allergens.add("tree_nut")
    if _ingredient_matches(ingredients, _SOY): allergens.add("soy")
    if _ingredient_matches(ingredients, {"통밀", "밀빵", "밀 파스타", "밀 크래커", "호밀빵"}): allergens.add("wheat")
    if _ingredient_matches(ingredients, {"메밀"}): allergens.add("buckwheat")
    if _ingredient_matches(ingredients, {"참깨", "참기름", "타히니"}): allergens.add("sesame")
    return sorted(allergens)


def _derive_metadata(ingredients: set[str], meal_type: str, healthy_fat: str | None) -> dict:
    protein_families = []
    for family, terms in (
        ("poultry", {"닭고기", "칠면조"}), ("red_meat", {"소고기", "돼지고기", "양고기"}),
        ("fish", _FISH), ("seafood", {"새우", "오징어", "문어"}),
        ("egg", {"달걀"}), ("dairy", _DAIRY), ("soy", _SOY),
        ("legume", _LEGUMES - _SOY),
    ):
        if _ingredient_matches(ingredients, terms): protein_families.append(family)

    animal_meat = _ingredient_matches(ingredients, _ANIMAL_MEAT)
    seafood = _ingredient_matches(ingredients, _SEAFOOD)
    egg_or_dairy = _ingredient_matches(ingredients, {"달걀"} | _DAIRY)
    if not animal_meat and not seafood and not egg_or_dairy:
        dietary_patterns = ["plant_based", "vegan_compatible"]
    elif not animal_meat and not seafood:
        dietary_patterns = ["vegetarian_compatible"]
    elif not animal_meat and seafood:
        dietary_patterns = ["pescatarian_compatible"]
    else:
        dietary_patterns = ["omnivore"]

    micronutrients = {"fiber", "b_vitamins"}
    if _ingredient_matches(ingredients, _FISH): micronutrients.add("omega3_food_source")
    if _ingredient_matches(ingredients, _DAIRY | _SOY | {"브로콜리", "아몬드"}): micronutrients.add("calcium")
    if _ingredient_matches(ingredients, _ANIMAL_MEAT | _LEGUMES | {"시금치", "해조류"}): micronutrients.add("iron")
    if _ingredient_matches(ingredients, {"토마토", "파프리카", "브로콜리", "베리류", "귤", "망고", "김치"}): micronutrients.add("vitamin_c")
    if _ingredient_matches(ingredients, _WHOLE_GRAINS | _LEGUMES | {"아보카도", "호두", "아몬드", "참깨"}): micronutrients.add("magnesium")

    contexts = ["everyday_training_meal", "post_workout_candidate"]
    if meal_type == "간식": contexts.append("portable_training_snack")
    return {
        "allergens": _derive_allergens(ingredients),
        "dietary_patterns": dietary_patterns,
        "protein_families": protein_families,
        "whole_grain": _ingredient_matches(ingredients, _WHOLE_GRAINS),
        "micronutrient_focus": sorted(micronutrients),
        "training_contexts": contexts,
        "digestibility": "moderate",
        "recovery_roles": ["carbohydrate_refuel", "protein_recovery"],
        "evidence_source_ids": ["acsm_2016", "issn_timing_2017", "usda_myplate"],
        "nutrition_verified": False,
        "review_status": "principle_based_unverified_portion",
    }


def _meal(
    option_id: str,
    meal_type: str,
    name: str,
    protein: str,
    carbohydrate: str,
    produce: str,
    ingredients: Iterable[str],
    *,
    healthy_fat: str | None = None,
    goals: Iterable[str] = GOALS,
    evidence_source_ids: Iterable[str] | None = None,
    training_contexts: Iterable[str] | None = None,
) -> dict:
    components = {
        "protein": protein,
        "carbohydrate": carbohydrate,
        "produce": produce,
    }
    balance_axes = ["단백질", "복합 탄수화물", "채소·과일"]
    if healthy_fat:
        components["healthy_fat"] = healthy_fat
        balance_axes.append("불포화지방")
    ingredient_list = list(ingredients)
    metadata = _derive_metadata(set(ingredient_list), meal_type, healthy_fat)
    if evidence_source_ids:
        metadata["evidence_source_ids"] = list(dict.fromkeys([
            *metadata["evidence_source_ids"], *evidence_source_ids]))
    if training_contexts:
        metadata["training_contexts"] = list(training_contexts)
    return {
        "option_id": option_id,
        "meal_type": meal_type,
        "name": name,
        "components": components,
        "ingredients": ingredient_list,
        "balance_axes": balance_axes,
        "goals": list(goals),
        "active": True,
        **metadata,
    }


MEAL_CATALOG = (
    # 아침: 기존 b01-b07 보존 + 신규 8종
    _meal("b01", "아침", "달걀과 오트밀 과일 아침", "달걀", "오트밀", "제철 과일", ["달걀", "오트밀", "과일", "호두"], healthy_fat="호두"),
    _meal("b02", "아침", "두부 채소 비빔밥", "구운 두부", "현미밥", "나물과 채소", ["두부", "현미밥", "채소", "참기름"], healthy_fat="참기름"),
    _meal("b03", "아침", "그릭요거트 오트 볼", "그릭요거트", "오트밀", "베리류", ["그릭요거트", "오트밀", "베리류", "아몬드"], healthy_fat="아몬드"),
    _meal("b04", "아침", "닭고기 고구마 샐러드", "닭고기", "고구마", "잎채소와 토마토", ["닭고기", "고구마", "잎채소", "토마토", "올리브유"], healthy_fat="올리브유"),
    _meal("b05", "아침", "통밀 달걀 샌드위치", "달걀", "통밀빵", "양상추와 토마토", ["달걀", "통밀빵", "양상추", "토마토", "아보카도"], healthy_fat="아보카도"),
    _meal("b06", "아침", "콩과 채소를 곁들인 현미죽", "콩과 두부", "현미죽", "버섯과 채소", ["콩", "두부", "현미", "버섯", "채소"]),
    _meal("b07", "아침", "연어 통밀 토스트", "연어", "통밀빵", "오이와 토마토", ["연어", "통밀빵", "오이", "토마토", "아보카도"], healthy_fat="아보카도"),
    _meal("b08", "아침", "닭고기 단호박 죽", "잘게 찢은 닭고기", "현미와 단호박", "시금치와 당근", ["닭고기", "현미", "단호박", "시금치", "당근"]),
    _meal("b09", "아침", "검은콩 달걀 주먹밥", "검은콩과 달걀", "현미밥", "김과 오이", ["검은콩", "달걀", "현미밥", "김", "오이", "참깨"], healthy_fat="참깨"),
    _meal("b10", "아침", "참치 채소 통밀랩", "참치", "통밀 또띠아", "양상추와 파프리카", ["참치", "통밀 또띠아", "양상추", "파프리카", "올리브유"], healthy_fat="올리브유"),
    _meal("b11", "아침", "렌틸콩 토마토 스튜와 통밀빵", "렌틸콩", "통밀빵", "토마토와 셀러리", ["렌틸콩", "통밀빵", "토마토", "셀러리"]),
    _meal("b12", "아침", "코티지치즈 사과 보리볼", "코티지치즈", "보리", "사과", ["코티지치즈", "보리", "사과", "호두"], healthy_fat="호두"),
    _meal("b13", "아침", "새우 채소 달걀볶음밥", "새우와 달걀", "현미밥", "브로콜리와 당근", ["새우", "달걀", "현미밥", "브로콜리", "당근", "참기름"], healthy_fat="참기름"),
    _meal("b14", "아침", "병아리콩 아보카도 토스트", "병아리콩", "통밀빵", "토마토와 루콜라", ["병아리콩", "통밀빵", "토마토", "루콜라", "아보카도"], healthy_fat="아보카도"),
    _meal("b15", "아침", "소고기 무국과 잡곡밥", "기름기 적은 소고기", "잡곡밥", "무와 대파", ["소고기", "잡곡밥", "무", "대파"]),
    _meal("b16", "아침", "바나나 베리 요거트 오트볼", "그릭요거트와 우유", "오트밀과 바나나", "베리류", ["그릭요거트", "우유", "오트밀", "바나나", "베리류"], evidence_source_ids=["ais_recipes"], training_contexts=["everyday_training_meal", "post_workout_candidate", "pre_workout_candidate"]),
    _meal("b17", "아침", "달걀 루콜라 통곡물 샌드위치", "달걀", "통밀빵", "루콜라와 토마토", ["달걀", "통밀빵", "루콜라", "토마토"], evidence_source_ids=["ais_recipes"], training_contexts=["everyday_training_meal", "post_workout_candidate", "pre_workout_candidate"]),
    _meal("b18", "아침", "두부 채소 쌀국수", "두부", "쌀국수", "청경채와 파프리카", ["두부", "대두", "쌀국수", "청경채", "파프리카"], evidence_source_ids=["ais_recipes"]),

    # 점심: 기존 l01-l07 보존 + 신규 8종
    _meal("l01", "점심", "닭고기 현미 균형 한 그릇", "닭고기", "현미밥", "구운 채소와 잎채소", ["닭고기", "현미밥", "구운 채소", "잎채소", "참깨"], healthy_fat="참깨"),
    _meal("l02", "점심", "연어 보리밥 정식", "구운 연어", "보리밥", "쌈채소와 나물", ["연어", "보리밥", "쌈채소", "나물"]),
    _meal("l03", "점심", "소고기 채소 메밀면", "기름기 적은 소고기", "메밀면", "양배추와 파프리카", ["소고기", "메밀면", "양배추", "파프리카", "참기름"], healthy_fat="참기름"),
    _meal("l04", "점심", "두부 병아리콩 곡물볼", "두부와 병아리콩", "잡곡밥", "다채로운 생채소", ["두부", "병아리콩", "잡곡밥", "생채소", "올리브유"], healthy_fat="올리브유"),
    _meal("l05", "점심", "고등어 현미 쌈밥", "구운 고등어", "현미밥", "쌈채소와 해조류", ["고등어", "현미밥", "쌈채소", "해조류"]),
    _meal("l06", "점심", "돼지고기 채소 덮밥", "기름기 적은 돼지고기", "잡곡밥", "버섯과 제철 채소", ["돼지고기", "잡곡밥", "버섯", "제철 채소"]),
    _meal("l07", "점심", "새우 렌틸 곡물 샐러드", "새우와 렌틸콩", "통곡물", "잎채소와 토마토", ["새우", "렌틸콩", "통곡물", "잎채소", "토마토", "올리브유"], healthy_fat="올리브유"),
    _meal("l08", "점심", "닭고기 메밀 비빔면", "닭고기", "메밀면", "오이와 양배추", ["닭고기", "메밀면", "오이", "양배추", "참깨"], healthy_fat="참깨"),
    _meal("l09", "점심", "두부 김치 보리비빔밥", "두부", "보리밥", "김치와 나물", ["두부", "보리밥", "김치", "나물", "참기름"], healthy_fat="참기름"),
    _meal("l10", "점심", "참치 콩 통밀 샌드위치", "참치와 흰콩", "통밀빵", "양상추와 토마토", ["참치", "흰콩", "통밀빵", "양상추", "토마토"]),
    _meal("l11", "점심", "소고기 버섯 보리 리소토", "기름기 적은 소고기", "보리", "버섯과 시금치", ["소고기", "보리", "버섯", "시금치", "올리브유"], healthy_fat="올리브유"),
    _meal("l12", "점심", "병아리콩 채소 카레와 현미밥", "병아리콩", "현미밥", "가지와 토마토", ["병아리콩", "현미밥", "가지", "토마토"]),
    _meal("l13", "점심", "오징어 채소 볶음과 잡곡밥", "오징어", "잡곡밥", "양배추와 양파", ["오징어", "잡곡밥", "양배추", "양파", "참기름"], healthy_fat="참기름"),
    _meal("l14", "점심", "닭고기 콩나물 국밥", "닭고기와 달걀", "현미밥", "콩나물과 대파", ["닭고기", "달걀", "현미밥", "콩나물", "대파"]),
    _meal("l15", "점심", "템페 채소 곡물볼", "템페", "퀴노아", "브로콜리와 당근", ["템페", "대두", "퀴노아", "브로콜리", "당근", "아보카도"], healthy_fat="아보카도"),
    _meal("l16", "점심", "닭고기 옥수수 통밀 파스타", "닭고기", "통밀 파스타와 옥수수", "버섯과 토마토", ["닭고기", "통밀 파스타", "옥수수", "버섯", "토마토"], evidence_source_ids=["ais_chicken_pasta", "ais_recipes"]),
    _meal("l17", "점심", "일본식 소고기 채소 덮밥", "기름기 적은 소고기", "현미밥", "브로콜리와 당근", ["소고기", "현미밥", "브로콜리", "당근", "참깨"], healthy_fat="참깨", evidence_source_ids=["ais_recipes"]),
    _meal("l18", "점심", "참치 토마토 통밀 파스타", "참치", "통밀 파스타", "토마토와 시금치", ["참치", "통밀 파스타", "토마토", "시금치", "올리브유"], healthy_fat="올리브유", evidence_source_ids=["ais_recipes"]),

    # 저녁: 기존 d01-d07 보존 + 신규 8종
    _meal("d01", "저녁", "흰살생선 채소구이와 잡곡밥", "흰살생선", "잡곡밥", "구운 제철 채소", ["흰살생선", "잡곡밥", "제철 채소", "올리브유"], healthy_fat="올리브유"),
    _meal("d02", "저녁", "두부 버섯 전골과 현미밥", "두부", "현미밥", "버섯과 배추", ["두부", "현미밥", "버섯", "배추"]),
    _meal("d03", "저녁", "닭고기 채소 수프와 통밀빵", "닭고기", "통밀빵", "토마토와 뿌리채소", ["닭고기", "통밀빵", "토마토", "뿌리채소"]),
    _meal("d04", "저녁", "소고기 두부 채소전골", "소고기와 두부", "잡곡밥", "버섯과 잎채소", ["소고기", "두부", "잡곡밥", "버섯", "잎채소"]),
    _meal("d05", "저녁", "연어 고구마 샐러드", "연어", "고구마", "잎채소와 브로콜리", ["연어", "고구마", "잎채소", "브로콜리", "올리브유"], healthy_fat="올리브유"),
    _meal("d06", "저녁", "렌틸콩 채소 카레와 현미밥", "렌틸콩", "현미밥", "가지와 파프리카", ["렌틸콩", "현미밥", "가지", "파프리카"]),
    _meal("d07", "저녁", "돼지고기 두부 김치찜과 잡곡밥", "기름기 적은 돼지고기와 두부", "잡곡밥", "김치와 곁들임 채소", ["돼지고기", "두부", "잡곡밥", "김치", "곁들임 채소"]),
    _meal("d08", "저녁", "닭고기 렌틸 토마토 스튜", "닭고기와 렌틸콩", "통밀빵", "토마토와 당근", ["닭고기", "렌틸콩", "통밀빵", "토마토", "당근"]),
    _meal("d09", "저녁", "고등어 무조림과 보리밥", "고등어", "보리밥", "무와 청경채", ["고등어", "보리밥", "무", "청경채"]),
    _meal("d10", "저녁", "두부 가지 된장덮밥", "두부와 대두", "현미밥", "가지와 애호박", ["두부", "대두", "현미밥", "가지", "애호박", "참기름"], healthy_fat="참기름"),
    _meal("d11", "저녁", "칠면조 채소 통밀 파스타", "칠면조", "통밀 파스타", "토마토와 시금치", ["칠면조", "통밀 파스타", "토마토", "시금치", "올리브유"], healthy_fat="올리브유"),
    _meal("d12", "저녁", "새우 두부 채소탕과 잡곡밥", "새우와 두부", "잡곡밥", "배추와 버섯", ["새우", "두부", "잡곡밥", "배추", "버섯"]),
    _meal("d13", "저녁", "소고기 브로콜리 볶음과 현미밥", "기름기 적은 소고기", "현미밥", "브로콜리와 파프리카", ["소고기", "현미밥", "브로콜리", "파프리카", "참깨"], healthy_fat="참깨"),
    _meal("d14", "저녁", "검은콩 단호박 칠리", "검은콩", "통곡물", "단호박과 토마토", ["검은콩", "통곡물", "단호박", "토마토", "아보카도"], healthy_fat="아보카도"),
    _meal("d15", "저녁", "돼지고기 숙주 메밀볶음", "기름기 적은 돼지고기", "메밀면", "숙주와 청경채", ["돼지고기", "메밀면", "숙주", "청경채", "참기름"], healthy_fat="참기름"),
    _meal("d16", "저녁", "두부 채소 그린커리와 쌀", "두부", "쌀밥", "가지와 파프리카", ["두부", "대두", "쌀밥", "가지", "파프리카"], evidence_source_ids=["ais_recipes"]),
    _meal("d17", "저녁", "양고기 시금치 감자 커리", "기름기 적은 양고기와 요거트", "감자와 쌀밥", "시금치와 토마토", ["양고기", "요거트", "감자", "쌀밥", "시금치", "토마토", "아몬드"], healthy_fat="아몬드", evidence_source_ids=["ais_lamb_curry", "ais_recipes"]),
    _meal("d18", "저녁", "닭고기 망고 채소 쌀볼", "닭고기", "쌀밥", "망고와 파프리카", ["닭고기", "쌀밥", "망고", "파프리카", "양배추"], evidence_source_ids=["ais_recipes"]),

    # 간식: 기존 s01-s06 보존 + 신규 9종
    _meal("s01", "간식", "그릭요거트와 과일", "그릭요거트", "제철 과일", "제철 과일", ["그릭요거트", "제철 과일", "호두"], healthy_fat="호두"),
    _meal("s02", "간식", "두부 과일 스무디", "연두부", "바나나", "바나나와 베리류", ["연두부", "대두", "바나나", "베리류"]),
    _meal("s03", "간식", "달걀과 고구마", "삶은 달걀", "고구마", "방울토마토", ["달걀", "고구마", "방울토마토"]),
    _meal("s04", "간식", "병아리콩 채소 딥", "병아리콩", "통밀빵", "오이와 파프리카", ["병아리콩", "통밀빵", "오이", "파프리카", "참깨"], healthy_fat="참깨"),
    _meal("s05", "간식", "코티지치즈와 과일", "코티지치즈", "제철 과일", "제철 과일", ["코티지치즈", "제철 과일"]),
    _meal("s06", "간식", "닭고기 통밀 미니랩", "닭고기", "통밀 또띠아", "양상추와 토마토", ["닭고기", "통밀 또띠아", "양상추", "토마토"]),
    _meal("s07", "간식", "에다마메와 귤", "에다마메", "귤", "귤", ["에다마메", "대두", "귤"]),
    _meal("s08", "간식", "참치 오이 통밀 크래커", "참치", "통밀 크래커", "오이", ["참치", "통밀 크래커", "오이"]),
    _meal("s09", "간식", "우유 오트 바나나 볼", "우유", "오트밀", "바나나", ["우유", "오트밀", "바나나", "땅콩버터"], healthy_fat="땅콩버터"),
    _meal("s10", "간식", "검은콩 단호박 미니볼", "검은콩", "단호박과 현미", "당근", ["검은콩", "단호박", "현미", "당근"]),
    _meal("s11", "간식", "훈제 연어 고구마 한입", "훈제 연어", "고구마", "오이", ["연어", "고구마", "오이"]),
    _meal("s12", "간식", "달걀 아보카도 통밀 토스트", "달걀", "통밀빵", "토마토", ["달걀", "통밀빵", "토마토", "아보카도"], healthy_fat="아보카도"),
    _meal("s13", "간식", "렌틸콩 채소 컵샐러드", "렌틸콩", "옥수수", "파프리카와 토마토", ["렌틸콩", "옥수수", "파프리카", "토마토", "올리브유"], healthy_fat="올리브유"),
    _meal("s14", "간식", "치즈 사과 호밀 오픈샌드", "치즈", "호밀빵", "사과", ["치즈", "호밀빵", "사과", "호두"], healthy_fat="호두"),
    _meal("s15", "간식", "새우 현미 채소 주먹밥", "새우", "현미밥", "당근과 김", ["새우", "현미밥", "당근", "김", "참깨"], healthy_fat="참깨"),
    _meal("s16", "간식", "바나나 요거트 오트 스무디", "그릭요거트와 우유", "바나나와 오트밀", "바나나", ["그릭요거트", "우유", "바나나", "오트밀"], evidence_source_ids=["ais_fruit_smoothie", "ais_recipes"], training_contexts=["post_workout_candidate", "pre_workout_candidate", "portable_training_snack"]),
    _meal("s17", "간식", "우유 망고 요거트 스무디", "우유와 요거트", "망고", "망고", ["우유", "요거트", "망고"], evidence_source_ids=["ais_mango_smoothie", "ais_recipes"], training_contexts=["post_workout_candidate", "pre_workout_candidate", "portable_training_snack"]),
    _meal("s18", "간식", "달걀 루콜라 통곡물 미니샌드", "달걀", "통밀빵", "루콜라와 토마토", ["달걀", "통밀빵", "루콜라", "토마토"], evidence_source_ids=["ais_recipes"], training_contexts=["post_workout_candidate", "pre_workout_candidate", "portable_training_snack"]),
)


def validate_catalog(catalog: Iterable[dict] = MEAL_CATALOG) -> bool:
    """Validate seed invariants; raise ``ValueError`` with actionable details."""
    rows = list(catalog)
    required_fields = {
        "option_id", "meal_type", "name", "components", "ingredients",
        "balance_axes", "goals", "active",
    }
    required_components = {"protein", "carbohydrate", "produce"}
    required_axes = {"단백질", "복합 탄수화물", "채소·과일"}

    if len(rows) != 72:
        raise ValueError(f"meal catalog must contain 72 rows, found {len(rows)}")
    counts = Counter(row.get("meal_type") for row in rows)
    expected_counts = {meal_type: 18 for meal_type in MEAL_TYPES}
    if counts != expected_counts:
        raise ValueError(f"each meal type must contain 18 rows: {dict(counts)}")

    ids = [row.get("option_id") for row in rows]
    if len(ids) != len(set(ids)):
        duplicates = sorted(key for key, value in Counter(ids).items() if value > 1)
        raise ValueError(f"duplicate option_id values: {duplicates}")

    for index, row in enumerate(rows):
        missing = required_fields - row.keys()
        if missing:
            raise ValueError(f"row {index} missing fields: {sorted(missing)}")
        if not isinstance(row["option_id"], str) or not row["option_id"].strip():
            raise ValueError(f"row {index} has invalid option_id")
        if row["meal_type"] not in MEAL_TYPES:
            raise ValueError(f"{row['option_id']} has unsupported meal_type")
        if not isinstance(row["name"], str) or not row["name"].strip():
            raise ValueError(f"{row['option_id']} has invalid name")
        if not required_components <= set(row["components"]):
            raise ValueError(f"{row['option_id']} lacks required components")
        if not required_axes <= set(row["balance_axes"]):
            raise ValueError(f"{row['option_id']} lacks required balance axes")
        if not row["ingredients"] or not all(isinstance(item, str) and item.strip() for item in row["ingredients"]):
            raise ValueError(f"{row['option_id']} has invalid ingredients")
        if not row["goals"] or not set(row["goals"]) <= set(GOALS):
            raise ValueError(f"{row['option_id']} has invalid goals")
        if row["active"] is not True:
            raise ValueError(f"{row['option_id']} must be active in the seed catalog")
        for field in (
            "allergens", "dietary_patterns", "protein_families",
            "micronutrient_focus", "training_contexts", "recovery_roles",
            "evidence_source_ids", "nutrition_verified", "review_status",
        ):
            if field not in row:
                raise ValueError(f"{row['option_id']} lacks {field}")
        if row["nutrition_verified"] is not False:
            raise ValueError(f"{row['option_id']} must not claim verified nutrition without portions")
    return True


__all__ = ["GOALS", "MEAL_CATALOG", "MEAL_TYPES", "validate_catalog"]
