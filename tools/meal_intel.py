"""Text-based meal parsing and qualitative diet classification.

The parser favors conservative confidence over over-claiming. It extracts broad
food axes, dish hints, portions, modifiers, and follow-up needs without turning
them into calorie or gram prescriptions.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

CORE_AXES = ("protein", "carb", "vegetable")
RISK_TAGS = ("sweet_drink", "dessert", "fried", "processed", "alcohol")
RISK_LABELS = {
    "sweet_drink": "달달한 음료",
    "dessert": "디저트",
    "fried": "튀김류",
    "processed": "가공식품",
    "alcohol": "술",
}
TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "meal_taxonomy.json"
FOOD_SPLIT_RE = re.compile(r"\s*(?:,|/|랑|와|과|하고|그리고|에다가|이랑|\+)\s*")


@lru_cache(maxsize=1)
def _taxonomy() -> dict:
    with TAXONOMY_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _matches(text: str, words: Iterable[str]) -> list[str]:
    return [word for word in words if word and word in text]


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _extract_meal_time(text: str, explicit_meal_time: str | None = None) -> str | None:
    if explicit_meal_time:
        return explicit_meal_time
    for meal_time, words in _taxonomy().get("meal_times", {}).items():
        if _matches(text, words):
            return meal_time
    return None


def _extract_portion_hints(text: str) -> list[dict]:
    hints = []
    for level, words in _taxonomy().get("portion_hints", {}).items():
        for term in _matches(text, words):
            hints.append({"term": term, "level": level})
    return hints


def _extract_modifiers(text: str) -> list[dict]:
    modifiers = []
    for modifier, words in _taxonomy().get("modifiers", {}).items():
        for term in _matches(text, words):
            modifiers.append({"term": term, "type": modifier})
    return modifiers


def _extract_dishes(text: str) -> list[dict]:
    dishes = []
    for name, spec in _taxonomy().get("dishes", {}).items():
        hits = _matches(text, spec.get("keywords", []))
        if hits:
            dishes.append({
                "name": name,
                "matched_terms": hits,
                "axes": spec.get("axes", []),
                "categories": spec.get("categories", []),
                "risk_flags": spec.get("risk_flags", []),
                "confidence": spec.get("confidence", 0.6),
                "notes": spec.get("notes"),
            })
    return sorted(dishes, key=lambda dish: dish["confidence"], reverse=True)


def _extract_category_hits(text: str) -> tuple[list[str], dict[str, list[str]], list[str]]:
    tags = []
    matched_terms: dict[str, list[str]] = {}
    risk_flags = []
    for tag, spec in _taxonomy().get("categories", {}).items():
        hits = _matches(text, spec.get("keywords", []))
        if not hits:
            continue
        tags.append(tag)
        matched_terms[tag] = hits
        if spec.get("role") == "risk":
            risk_flags.append(tag)
    return tags, matched_terms, risk_flags


def _candidate_food_segments(text: str) -> list[str]:
    cleaned = text
    for word in ["아침", "점심", "저녁", "야식", "간식", "먹었어", "먹음", "먹었다"]:
        cleaned = cleaned.replace(word, " ")
    return [
        segment.strip()
        for segment in FOOD_SPLIT_RE.split(cleaned)
        if segment.strip()
    ]


def _food_items(text: str, dishes: list[dict], matched_terms: dict[str, list[str]]) -> list[dict]:
    items: list[dict] = []
    used_names = set()
    for dish in dishes:
        items.append({
            "name": dish["name"],
            "source": "dish",
            "axes": dish["axes"],
            "risk_flags": dish["risk_flags"],
            "confidence": dish["confidence"],
        })
        used_names.add(dish["name"])

    for segment in _candidate_food_segments(text):
        segment_axes = [
            axis for axis in CORE_AXES
            if any(term in segment for term in matched_terms.get(axis, []))
        ]
        segment_risks = [
            risk for risk in RISK_TAGS
            if any(term in segment for term in matched_terms.get(risk, []))
        ]
        if not segment_axes and not segment_risks:
            continue
        if segment in used_names:
            continue
        items.append({
            "name": segment,
            "source": "text_segment",
            "axes": segment_axes,
            "risk_flags": segment_risks,
            "confidence": 0.62 if segment_axes else 0.52,
        })
    return items


def _uncertainty_signals(text: str, tags: list[str], dishes: list[dict]) -> list[str]:
    signals = _matches(text, _taxonomy().get("uncertainty_terms", []))
    if not tags and text:
        signals.append("no_food_axis_detected")
    if any(dish["confidence"] < 0.5 for dish in dishes):
        signals.append("broad_dish_name")
    return _unique(signals)


def _confidence_level(score: float) -> str:
    if score >= 0.78:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _confidence_score(
    tags: list[str],
    dishes: list[dict],
    portion_hints: list[dict],
    uncertainty_signals: list[str],
    text: str,
) -> float:
    if not text:
        return 0.0

    score = 0.3
    score += min(0.36, len([axis for axis in CORE_AXES if axis in tags]) * 0.12)
    score += min(0.18, len(dishes) * 0.09)
    if portion_hints:
        score += 0.06
    if any(tag in tags for tag in RISK_TAGS):
        score += 0.04
    score -= min(0.3, len(uncertainty_signals) * 0.12)
    return round(max(0.0, min(score, 0.95)), 2)


def _follow_up_questions(
    confidence_level: str,
    missing_axes: list[str],
    uncertainty_signals: list[str],
    food_items: list[dict],
) -> list[str]:
    questions = []
    if confidence_level == "low" or "broad_dish_name" in uncertainty_signals:
        questions.append("단백질 반찬이 있었는지만 알려주면 더 정확히 볼게요.")
    if "no_food_axis_detected" in uncertainty_signals:
        questions.append("먹은 음식 이름을 한두 개만 더 적어주세요.")
    if "protein" in missing_axes and food_items:
        questions.append("고기, 계란, 두부, 생선 같은 단백질이 있었나요?")
    if "vegetable" in missing_axes and food_items:
        questions.append("채소나 김치, 샐러드가 같이 있었나요?")
    return _unique(questions)[:2]


def _balance_flag(
    text: str,
    tags: list[str],
    missing_axes: list[str],
    risk_flags: list[str],
    confidence_level: str,
) -> str:
    if not text or not tags:
        return "unclear"
    if "skipped" in tags:
        return "skipped_meal"
    if confidence_level == "low":
        return "needs_more_info"
    if missing_axes:
        return "needs_balance"
    if risk_flags:
        return "watch_extras"
    return "balanced"


def classify_meal_text(
    meal_text: str | None,
    *,
    meal_time: str | None = None,
    recent_classifications: list[dict] | None = None,
) -> dict:
    text = (meal_text or "").strip().lower()
    category_tags, matched_terms, category_risks = _extract_category_hits(text)
    dishes = _extract_dishes(text)

    dish_axes = [axis for dish in dishes for axis in dish.get("axes", [])]
    dish_risks = [risk for dish in dishes for risk in dish.get("risk_flags", [])]
    tags = _unique([*category_tags, *dish_axes, *dish_risks])
    risk_flags = _unique([*category_risks, *dish_risks])
    portion_hints = _extract_portion_hints(text)
    modifiers = _extract_modifiers(text)
    food_items = _food_items(text, dishes, matched_terms)
    uncertainty_signals = _uncertainty_signals(text, tags, dishes)
    recent_resolution = _recent_resolution(text, tags, recent_classifications)
    if recent_resolution:
        tags = _unique([*tags, *recent_resolution["inferred_axes"]])
        risk_flags = _unique([*risk_flags, *recent_resolution["inferred_risk_flags"]])

    missing_axes = [axis for axis in CORE_AXES if axis not in tags]
    if "skipped" in tags:
        missing_axes = list(CORE_AXES)

    score = _confidence_score(tags, dishes, portion_hints, uncertainty_signals, text)
    confidence = _confidence_level(score)
    balance_flag = _balance_flag(text, tags, missing_axes, risk_flags, confidence)
    follow_up_questions = _follow_up_questions(
        confidence, missing_axes, uncertainty_signals, food_items)

    return {
        "meal_tags": tags,
        "matched_terms": matched_terms,
        "missing_axes": missing_axes,
        "risk_flags": risk_flags,
        "balance_flag": balance_flag,
        "meal_score": len([axis for axis in CORE_AXES if axis in tags]),
        "food_items": food_items,
        "dish_matches": dishes,
        "meal_time_detected": _extract_meal_time(text, meal_time),
        "portion_hints": portion_hints,
        "modifiers": modifiers,
        "uncertainty_signals": uncertainty_signals,
        "confidence": confidence,
        "confidence_score": score,
        "needs_follow_up": bool(follow_up_questions),
        "follow_up_questions": follow_up_questions,
        "recent_resolution": recent_resolution,
        "external_reference_mode": (
            _taxonomy().get("external_reference_policy", {}).get("mode")
        ),
    }


def _recent_resolution(
    text: str,
    current_tags: list[str],
    recent_classifications: list[dict] | None,
) -> dict | None:
    if not recent_classifications:
        return None
    vague_terms = _taxonomy().get("uncertainty_terms", [])
    if not _matches(text, vague_terms):
        return None

    axis_counts = {axis: 0 for axis in CORE_AXES}
    risk_counts: dict[str, int] = {}
    for classification in recent_classifications:
        for axis in CORE_AXES:
            if axis in classification.get("meal_tags", []):
                axis_counts[axis] += 1
        for risk in classification.get("risk_flags", []):
            risk_counts[risk] = risk_counts.get(risk, 0) + 1

    threshold = max(2, len(recent_classifications) // 2)
    inferred_axes = [
        axis for axis, count in axis_counts.items()
        if axis not in current_tags and count >= threshold
    ]
    inferred_risk_flags = [
        risk for risk, count in risk_counts.items()
        if risk not in current_tags and count >= threshold
    ]
    if not inferred_axes and not inferred_risk_flags:
        return None
    return {
        "basis": "recent_user_meals",
        "matched_vague_terms": _matches(text, vague_terms),
        "sample_size": len(recent_classifications),
        "inferred_axes": inferred_axes,
        "inferred_risk_flags": inferred_risk_flags,
        "note": "최근 기록 기반 추정이며, 이번 입력에 명시된 음식이 우선입니다.",
    }


def meal_feedback(classification: dict) -> str:
    flag = classification["balance_flag"]
    missing = classification["missing_axes"]
    risks = classification["risk_flags"]
    confidence = classification.get("confidence")

    if flag == "unclear":
        return "식단 구성이 선명하지 않아요. 다음 기록엔 주된 단백질, 탄수화물, 채소 축을 같이 적어주세요."
    if flag == "needs_more_info":
        question = (classification.get("follow_up_questions") or ["구성을 조금만 더 알려주세요."])[0]
        return f"기록이 조금 넓게 들어와서 단정하긴 어려워요. {question}"
    if flag == "skipped_meal":
        return "끼니를 거른 흐름이 보여요. 다음 끼니는 무리하게 몰아 먹기보다 단백질과 탄수화물부터 안정적으로 챙겨봐요."
    if "protein" in missing:
        return "탄수화물이나 곁들임은 보이지만 단백질 축이 부족해 보여요. 다음 끼니엔 고기, 생선, 계란, 두부 같은 단백질을 먼저 보강해봐요."
    if "vegetable" in missing:
        return "단백질과 탄수화물은 보이지만 채소 축이 적어 보여요. 다음 끼니엔 샐러드, 나물, 김치, 쌈채소 중 하나를 붙여봐요."
    if "carb" in missing:
        return "단백질과 채소는 괜찮아 보여요. 운동 전후라면 밥, 고구마, 오트 같은 탄수화물도 적당히 챙기면 좋아요."
    if risks:
        risk_text = "·".join(RISK_LABELS.get(risk, risk) for risk in risks)
        return f"기본 축은 갖췄지만 {risk_text} 쪽 변수가 보여요. 제한보다 빈도만 차분히 줄여봐요."
    if confidence == "medium":
        return "큰 축은 균형 있어 보여요. 다만 양이나 곁들임이 더 보이면 다음 조정은 더 정확해질 수 있어요."
    return "단백질, 채소, 탄수화물 구성이 꽤 균형 있어 보여요. 이 흐름 유지해봐요."


def summarize_meal_classifications(classifications: list[dict]) -> dict:
    if not classifications:
        return {
            "meal_count": 0,
            "common_missing_axes": [],
            "frequent_risk_flags": [],
            "average_score": 0.0,
            "reliable_meal_count": 0,
            "low_confidence_count": 0,
            "follow_up_needed_count": 0,
            "common_uncertainty_signals": [],
        }

    missing_counts: dict[str, int] = {axis: 0 for axis in CORE_AXES}
    risk_counts: dict[str, int] = {}
    uncertainty_counts: dict[str, int] = {}
    total_score = 0
    low_confidence_count = 0
    follow_up_needed_count = 0
    reliable_count = 0
    for classification in classifications:
        total_score += classification.get("meal_score", 0)
        is_low_confidence = classification.get("confidence") == "low"
        low_confidence_count += 1 if is_low_confidence else 0
        follow_up_needed_count += 1 if classification.get("needs_follow_up") else 0
        if not is_low_confidence:
            reliable_count += 1
            for axis in classification.get("missing_axes", []):
                if axis in missing_counts:
                    missing_counts[axis] += 1
        for risk in classification.get("risk_flags", []):
            risk_counts[risk] = risk_counts.get(risk, 0) + 1
        for signal in classification.get("uncertainty_signals", []):
            uncertainty_counts[signal] = uncertainty_counts.get(signal, 0) + 1

    meal_count = len(classifications)
    missing_threshold = reliable_count / 2 if reliable_count else meal_count + 1
    risk_threshold = meal_count / 2
    return {
        "meal_count": meal_count,
        "common_missing_axes": [
            axis for axis, count in missing_counts.items()
            if count >= missing_threshold
        ],
        "frequent_risk_flags": [
            risk for risk, count in risk_counts.items() if count >= risk_threshold
        ],
        "average_score": round(total_score / meal_count, 2),
        "reliable_meal_count": reliable_count,
        "low_confidence_count": low_confidence_count,
        "follow_up_needed_count": follow_up_needed_count,
        "common_uncertainty_signals": [
            signal for signal, count in uncertainty_counts.items()
            if count >= risk_threshold
        ],
    }
