"""Qualitative, preference-aware meal plan selection.

This module deliberately owns only food selection.  Rendering persona copy and
creating calendar events remain the caller's responsibility.  Suggestions are
plate-composition guidance, not calorie or gram prescriptions.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Iterable, Sequence


MEAL_TYPES = ("아침", "점심", "저녁", "간식")

_GOAL_ALIASES = {
    "증량": "증량", "벌크": "증량", "벌크업": "증량", "gain": "증량", "bulk": "증량",
    "감량": "감량", "다이어트": "감량", "cut": "감량", "loss": "감량",
    "유지": "유지", "maintain": "유지", "maintenance": "유지",
}

# Group entries make broad statements such as "생선은 싫어" or
# "견과류 알레르기" useful when filtering concrete ingredients.
_FOOD_GROUPS = {
    "생선": {"생선", "연어", "고등어", "참치", "흰살생선"},
    "해산물": {"생선", "연어", "고등어", "참치", "흰살생선", "새우", "오징어"},
    "갑각류": {"새우"},
    "견과류": {"견과류", "아몬드", "호두", "땅콩", "땅콩버터"},
    "유제품": {"우유", "그릭요거트", "요거트", "치즈", "코티지치즈"},
    "달걀": {"달걀", "계란"},
    "콩": {"콩", "두부", "병아리콩", "렌틸콩", "에다마메", "대두", "검은콩", "템페"},
    "육류": {"닭고기", "닭가슴살", "소고기", "돼지고기"},
    "대두": {"대두", "두부", "연두부", "템페", "에다마메"},
    "밀": {"밀", "통밀빵", "통밀 또띠아", "통밀 파스타", "호밀빵", "통밀 크래커"},
    "참깨": {"참깨", "참기름", "타히니"},
}

_ALLERGEN_TAGS = {
    "달걀": {"egg"}, "유제품": {"milk"}, "우유": {"milk"},
    "생선": {"fish"}, "해산물": {"fish", "crustacean", "mollusk"},
    "갑각류": {"crustacean"}, "새우": {"crustacean"}, "오징어": {"mollusk"},
    "견과류": {"tree_nut", "peanut"}, "땅콩": {"peanut"},
    "콩": {"soy"}, "대두": {"soy"}, "밀": {"wheat"}, "글루텐": {"wheat"},
    "메밀": {"buckwheat"}, "참깨": {"sesame"},
}

_ALIASES = {
    "계란": "달걀", "닭": "닭고기", "치킨": "닭고기", "닭가슴살": "닭고기",
    "소고기": "소고기", "쇠고기": "소고기", "돼지고기": "돼지고기",
    "연어": "연어", "고등어": "고등어", "참치": "참치", "생선": "생선",
    "해산물": "해산물", "갑각류": "갑각류", "새우": "새우",
    "오징어": "오징어",
    "두부": "두부", "콩": "콩", "병아리콩": "병아리콩", "렌틸콩": "렌틸콩",
    "대두": "대두", "검은콩": "검은콩", "템페": "템페",
    "견과류": "견과류", "아몬드": "아몬드", "호두": "호두", "땅콩": "땅콩",
    "땅콩버터": "땅콩버터", "유제품": "유제품", "우유": "우유",
    "요거트": "요거트", "그릭요거트": "그릭요거트", "치즈": "치즈",
    "유당불내증": "유제품", "유당불내": "유제품",
    "밀": "밀", "글루텐": "글루텐", "대두": "대두", "참깨": "참깨",
    "달걀": "달걀", "오트밀": "오트밀", "현미": "현미밥", "현미밥": "현미밥",
    "고구마": "고구마", "통밀빵": "통밀빵", "메밀": "메밀면",
}

_ALLERGY = re.compile(r"알레르기|알러지|먹으면\s*(?:안\s*돼|안됨|아파)|못\s*먹")
_DISLIKE = re.compile(r"싫(?:어|습니다)|안\s*좋아|제외|빼\s*줘|피하고|못\s*먹")
_LIKE = re.compile(r"좋아|선호|즐겨|자주\s*먹")
_UNSAFE = re.compile(
    r"\d[\d,.]*\s*(?:kcal|cal|칼로리|g|그램)|굶|금식|단식|끼니\s*(?:를\s*)?거르|"
    r"(?:아침|점심|저녁)\s*(?:은|을|는)?\s*(?:안\s*먹|먹지\s*않)", re.IGNORECASE,
)

_GOAL_FOCUS = {
    "증량": "끼니를 거르지 않고 운동 전후에도 단백질과 탄수화물 공급을 안정적으로 이어가는 구성",
    "감량": "단백질과 식이섬유가 풍부한 식품을 함께 두어 포만감과 근육 보존을 고려한 구성",
    "유지": "서로 다른 단백질원과 제철 채소를 순환해 영양 다양성과 지속 가능성을 챙기는 구성",
}


@dataclass(frozen=True)
class MealOption:
    id: str
    meal_type: str
    name: str
    components: dict[str, str]
    ingredients: frozenset[str]
    balance_axes: tuple[str, ...]
    goals: frozenset[str] = frozenset({"증량", "감량", "유지"})
    allergens: frozenset[str] = frozenset()
    selection_weight: int = 100
    nutrition_metadata: dict | None = None


def _option(option_id: str, meal_type: str, name: str, *, protein: str,
            carbohydrate: str, produce: str, healthy_fat: str | None = None,
            ingredients: Iterable[str], goals: Iterable[str] = ("증량", "감량", "유지")) -> MealOption:
    components = {"protein": protein, "carbohydrate": carbohydrate, "produce": produce}
    axes = ["단백질", "복합 탄수화물", "채소·과일"]
    if healthy_fat:
        components["healthy_fat"] = healthy_fat
        axes.append("불포화지방")
    return MealOption(option_id, meal_type, name, components, frozenset(ingredients), tuple(axes), frozenset(goals))


_OPTIONS = (
    # Breakfast: protein + fibre-rich carbohydrate + produce, with culturally
    # familiar choices rather than a single bodybuilding template.
    _option("b01", "아침", "달걀과 오트밀 과일 아침", protein="달걀", carbohydrate="오트밀", produce="제철 과일", healthy_fat="호두", ingredients={"달걀", "오트밀", "과일", "호두"}),
    _option("b02", "아침", "두부 채소 비빔밥", protein="구운 두부", carbohydrate="현미밥", produce="나물과 채소", healthy_fat="참기름", ingredients={"두부", "현미밥", "채소"}),
    _option("b03", "아침", "그릭요거트 오트 볼", protein="그릭요거트", carbohydrate="오트밀", produce="베리류", healthy_fat="아몬드", ingredients={"그릭요거트", "오트밀", "과일", "아몬드"}),
    _option("b04", "아침", "닭고기 고구마 샐러드", protein="닭고기", carbohydrate="고구마", produce="잎채소와 토마토", healthy_fat="올리브유", ingredients={"닭고기", "고구마", "채소"}),
    _option("b05", "아침", "통밀 달걀 샌드위치", protein="달걀", carbohydrate="통밀빵", produce="양상추와 토마토", healthy_fat="아보카도", ingredients={"달걀", "통밀빵", "채소", "아보카도"}),
    _option("b06", "아침", "콩과 채소를 곁들인 현미죽", protein="콩과 두부", carbohydrate="현미죽", produce="버섯과 채소", ingredients={"콩", "두부", "현미밥", "채소"}),
    _option("b07", "아침", "연어 통밀 토스트", protein="연어", carbohydrate="통밀빵", produce="오이와 토마토", healthy_fat="아보카도", ingredients={"연어", "통밀빵", "채소", "아보카도"}),
    # Lunch
    _option("l01", "점심", "닭고기 현미 균형 한 그릇", protein="닭고기", carbohydrate="현미밥", produce="구운 채소와 잎채소", healthy_fat="참깨", ingredients={"닭고기", "현미밥", "채소"}),
    _option("l02", "점심", "연어 보리밥 정식", protein="구운 연어", carbohydrate="보리밥", produce="쌈채소와 나물", ingredients={"연어", "보리밥", "채소"}),
    _option("l03", "점심", "소고기 채소 메밀면", protein="기름기 적은 소고기", carbohydrate="메밀면", produce="양배추와 파프리카", healthy_fat="참기름", ingredients={"소고기", "메밀면", "채소"}),
    _option("l04", "점심", "두부 병아리콩 곡물볼", protein="두부와 병아리콩", carbohydrate="잡곡밥", produce="다채로운 생채소", healthy_fat="올리브유", ingredients={"두부", "병아리콩", "잡곡밥", "채소"}),
    _option("l05", "점심", "고등어 현미 쌈밥", protein="구운 고등어", carbohydrate="현미밥", produce="쌈채소와 해조류", ingredients={"고등어", "현미밥", "채소"}),
    _option("l06", "점심", "돼지고기 채소 덮밥", protein="기름기 적은 돼지고기", carbohydrate="잡곡밥", produce="버섯과 제철 채소", ingredients={"돼지고기", "잡곡밥", "채소"}),
    _option("l07", "점심", "새우 렌틸 곡물 샐러드", protein="새우와 렌틸콩", carbohydrate="통곡물", produce="잎채소와 토마토", healthy_fat="올리브유", ingredients={"새우", "렌틸콩", "통곡물", "채소"}),
    # Dinner
    _option("d01", "저녁", "흰살생선 채소구이와 잡곡밥", protein="흰살생선", carbohydrate="잡곡밥", produce="구운 제철 채소", healthy_fat="올리브유", ingredients={"흰살생선", "잡곡밥", "채소"}),
    _option("d02", "저녁", "두부 버섯 전골과 현미밥", protein="두부", carbohydrate="현미밥", produce="버섯과 배추", ingredients={"두부", "현미밥", "채소"}),
    _option("d03", "저녁", "닭고기 채소 수프와 통밀빵", protein="닭고기", carbohydrate="통밀빵", produce="토마토와 뿌리채소", ingredients={"닭고기", "통밀빵", "채소"}),
    _option("d04", "저녁", "소고기 두부 채소전골", protein="소고기와 두부", carbohydrate="잡곡밥", produce="버섯과 잎채소", ingredients={"소고기", "두부", "잡곡밥", "채소"}),
    _option("d05", "저녁", "연어 고구마 샐러드", protein="연어", carbohydrate="고구마", produce="잎채소와 브로콜리", healthy_fat="올리브유", ingredients={"연어", "고구마", "채소"}),
    _option("d06", "저녁", "렌틸콩 채소 카레와 현미밥", protein="렌틸콩", carbohydrate="현미밥", produce="가지와 파프리카", ingredients={"렌틸콩", "현미밥", "채소"}),
    _option("d07", "저녁", "돼지고기 두부 김치찜과 잡곡밥", protein="기름기 적은 돼지고기와 두부", carbohydrate="잡곡밥", produce="김치와 곁들임 채소", ingredients={"돼지고기", "두부", "잡곡밥", "채소"}),
    # Snacks remain combinations, not isolated supplements.
    _option("s01", "간식", "그릭요거트와 과일", protein="그릭요거트", carbohydrate="제철 과일", produce="제철 과일", healthy_fat="호두", ingredients={"그릭요거트", "과일", "호두"}),
    _option("s02", "간식", "두부 과일 스무디", protein="연두부", carbohydrate="바나나", produce="바나나와 베리류", ingredients={"두부", "과일"}),
    _option("s03", "간식", "달걀과 고구마", protein="삶은 달걀", carbohydrate="고구마", produce="방울토마토", ingredients={"달걀", "고구마", "채소"}),
    _option("s04", "간식", "병아리콩 채소 딥", protein="병아리콩", carbohydrate="통밀빵", produce="오이와 파프리카", healthy_fat="참깨", ingredients={"병아리콩", "통밀빵", "채소"}),
    _option("s05", "간식", "코티지치즈와 과일", protein="코티지치즈", carbohydrate="제철 과일", produce="제철 과일", ingredients={"코티지치즈", "과일"}),
    _option("s06", "간식", "닭고기 통밀 미니랩", protein="닭고기", carbohydrate="통밀 또띠아", produce="양상추와 토마토", ingredients={"닭고기", "통밀빵", "채소"}),
)


def normalize_meal_goal(goal: str | None) -> str:
    if not goal:
        return "유지"
    raw = goal.strip().casefold()
    for alias, normalized in _GOAL_ALIASES.items():
        if alias.casefold() in raw:
            return normalized
    return "유지"


def _expanded_foods(foods: Iterable[str]) -> set[str]:
    expanded: set[str] = set()
    for food in foods:
        canonical = _ALIASES.get(food, food)
        expanded.add(canonical)
        expanded.update(_FOOD_GROUPS.get(canonical, set()))
    return expanded


def parse_food_preferences(text: str | None) -> dict:
    """Extract explicit Korean food likes, dislikes and allergies.

    Unsafe numeric restriction/fasting clauses are ignored rather than treated
    as preferences.  Allergy wins over dislike, and dislike wins over like.
    """
    result = {"liked": [], "disliked": [], "allergens": [], "ignored_constraints": []}
    if not isinstance(text, str) or not text.strip():
        return result

    clauses = [c.strip() for c in re.split(r"[,.!?;\n]+", text) if c.strip()]
    found = {"liked": set(), "disliked": set(), "allergens": set()}
    aliases = sorted(_ALIASES, key=len, reverse=True)
    food_pattern = re.compile("|".join(map(re.escape, aliases)))

    for clause in clauses:
        if _UNSAFE.search(clause):
            result["ignored_constraints"].append(clause)
            # A safe food statement after a dangerous constraint is commonly
            # joined by "...하고"; retain only that trailing statement.
            parts = re.split(r"(?:먹고|하고)\s+(?=[가-힣A-Za-z].*(?:좋아|싫어|알레르기|알러지|못\s*먹))", clause, maxsplit=1)
            if len(parts) == 1:
                continue
            clause = parts[-1]

        matches = list(food_pattern.finditer(clause))
        for match in matches:
            canonical = _ALIASES[match.group(0)]
            if match.group(0).startswith("유당불내"):
                found["allergens"].add(canonical)
                continue
            # The first sentiment *after* a food owns that food.  This handles
            # both grouped foods ("닭고기와 두부를 좋아해") and mixed clauses
            # ("생선은 싫어하고 닭고기는 좋아해") without leaking sentiment
            # across the connector.
            suffix = clause[match.end():]
            sentiments = []
            for kind, pattern in (("allergens", _ALLERGY), ("disliked", _DISLIKE), ("liked", _LIKE)):
                sentiment = pattern.search(suffix)
                if sentiment:
                    sentiments.append((sentiment.start(), kind))
            if sentiments:
                found[min(sentiments)[1]].add(canonical)
                continue
            # Also support prefix notation such as "알레르기: 견과류".
            prefix = clause[:match.start()]
            if _ALLERGY.search(prefix):
                found["allergens"].add(canonical)
            elif _DISLIKE.search(prefix):
                found["disliked"].add(canonical)
            elif _LIKE.search(prefix):
                found["liked"].add(canonical)

    allergen_expanded = _expanded_foods(found["allergens"])
    disliked_expanded = _expanded_foods(found["disliked"])
    found["liked"] -= allergen_expanded | disliked_expanded
    found["disliked"] -= allergen_expanded
    for key in ("liked", "disliked", "allergens"):
        result[key] = sorted(found[key])
    return result


def _normalized_meal_types(meal_types: Sequence[str] | None) -> list[str]:
    requested = list(meal_types or ("아침", "점심", "저녁"))
    aliases = {"breakfast": "아침", "lunch": "점심", "dinner": "저녁", "snack": "간식"}
    normalized = [aliases.get(str(value).strip().casefold(), str(value).strip()) for value in requested]
    invalid = [value for value in normalized if value not in MEAL_TYPES]
    if invalid:
        raise ValueError(f"unsupported meal types: {invalid}")
    return normalized


def _coerce_options(options: Sequence[dict]) -> tuple[MealOption, ...]:
    if not options:
        raise ValueError("meal options must come from the isolated meal database")
    return tuple(
        MealOption(
            id=str(option["option_id"]),
            meal_type=str(option["meal_type"]),
            name=str(option["name"]),
            components=dict(option["components"]),
            ingredients=frozenset(option["ingredients"]),
            balance_axes=tuple(option["balance_axes"]),
            goals=frozenset(option.get("goals", ("증량", "감량", "유지"))),
            allergens=frozenset(option.get("allergens", ())),
            selection_weight=max(1, int(option.get("selection_weight", 100))),
            nutrition_metadata={
                key: option.get(key)
                for key in (
                    "dietary_patterns", "protein_families", "whole_grain",
                    "micronutrient_focus", "training_contexts", "digestibility",
                    "recovery_roles", "evidence_source_ids", "nutrition_verified",
                    "review_status",
                )
            },
        )
        for option in options
    )


def build_meal_plan(goal: str | None, meal_types: Sequence[str] | None = None,
                    preferences: str | None = None, *, options: Sequence[dict],
                    seed: int | str | None = None,
                    rng: random.Random | None = None,
                    ) -> dict:
    """Select a varied qualitative plan suitable for ``generate_meal_plan``.

    ``seed`` makes tests/callers reproducible.  In production, omitting it uses
    system-seeded randomness.  An option is never repeated within one plan.
    """
    if seed is not None and rng is not None:
        raise ValueError("pass either seed or rng, not both")
    picker = rng or random.Random(seed)
    normalized_goal = normalize_meal_goal(goal)
    requested_types = _normalized_meal_types(meal_types)
    available_options = _coerce_options(options)
    profile = parse_food_preferences(preferences)
    excluded = _expanded_foods(profile["disliked"]) | _expanded_foods(profile["allergens"])
    excluded_allergen_tags = set().union(*(
        _ALLERGEN_TAGS.get(food, set()) for food in profile["allergens"]
    )) if profile["allergens"] else set()
    liked = _expanded_foods(profile["liked"])
    used_ids: set[str] = set()
    used_primary: set[str] = set()
    meals: list[dict] = []

    for meal_type in requested_types:
        candidates = [
            option for option in available_options
            if option.meal_type == meal_type
            and normalized_goal in option.goals
            and option.id not in used_ids
            and not (option.ingredients & excluded)
            and not (option.allergens & excluded_allergen_tags)
        ]
        if not candidates:
            raise ValueError(f"'{meal_type}'에 알레르기·비선호 조건을 만족하는 식단 후보가 없습니다")

        def score(option: MealOption) -> tuple[int, int]:
            # Explicit likes lead selection, while a smaller overlap penalty
            # prevents every meal from becoming the same favourite ingredient.
            return (len(option.ingredients & liked) * 4 - len(option.ingredients & used_primary) * 5,
                    -len(option.ingredients & used_primary))

        best_score = max(score(option) for option in candidates)
        finalists = [option for option in candidates if score(option) == best_score]
        selected = picker.choices(
            finalists,
            weights=[option.selection_weight for option in finalists],
            k=1,
        )[0]
        matched_likes = sorted(selected.ingredients & liked)
        used_ids.add(selected.id)
        used_primary.update(selected.ingredients - {"채소", "과일", "현미밥", "잡곡밥", "통밀빵"})
        reason = (
            f"사용자의 음식 선호를 반영하면서 {_GOAL_FOCUS[normalized_goal]}"
            if matched_likes else
            _GOAL_FOCUS[normalized_goal]
        )
        meals.append({
            "option_id": selected.id,
            "meal_type": selected.meal_type,
            "name": selected.name,
            "components": dict(selected.components),
            "balance_axes": list(selected.balance_axes),
            "matched_preferences": matched_likes,
            "selection_reason": reason,
            "allergens": sorted(selected.allergens),
            **(selected.nutrition_metadata or {}),
        })

    return {
        "goal": normalized_goal,
        "goal_focus": _GOAL_FOCUS[normalized_goal],
        "meals": meals,
        "preference_profile": profile,
        "professional_principles": [
            "매 끼니 단백질 공급원과 복합 탄수화물, 채소·과일을 함께 구성",
            "알레르기 음식은 제외하고 비선호 음식은 대체 식품으로 전환",
            "정확한 칼로리나 중량 대신 지속 가능한 식사 구성과 다양성을 우선",
        ],
    }


__all__ = ["MEAL_TYPES", "build_meal_plan", "normalize_meal_goal", "parse_food_preferences"]
