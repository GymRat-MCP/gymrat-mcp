"""식단 플랜 + 전반 코칭

⚠️ 가드레일(중요):
- 정확 칼로리/그램 처방 ❌ → 질적 가이드만 ("아침: 단백질 위주, 계란+오트밀 정도")
- 하드한 제한식 ❌, 식이강박 보호
- 페르소나(천사/악마/코치/현실파이터)는 '말투'만 — 가드레일은 항상 적용
"""
from datetime import datetime, time, timedelta
import re

from db.session import SessionLocal
from db.models import User, WeightLog, InbodyLog, WorkoutLog, MealLog
from tools.analysis import analyze_trend
from tools.meal_intel import (
    classify_meal_text,
    summarize_meal_classifications,
)
from meal_db.repository import load_active_meal_options
from tools.meal_planner import MEAL_TYPES, build_meal_plan
from tools.persona import (
    DEFAULT_PERSONA,
    apply_persona,
    normalize_persona,
    persona_response_fields,
)
from tools.profile import normalize_goal


_PERSONA_ALIASES = {
    "angel": "천사",
    "devil": "악마",
    "coach": "코치",
    "realist": "현실파이터",
    "reality fighter": "현실파이터",
    "reality-fighter": "현실파이터",
}

_UNSAFE_PREFERENCE_PATTERNS = {
    "exact_calorie_limit": re.compile(
        r"(?:\d[\d,.]*\s*(?:kcal|cal|칼로리)|(?:kcal|cal|칼로리)\s*\d[\d,.]*)",
        re.IGNORECASE,
    ),
    "exact_gram_limit": re.compile(
        r"(?:\d[\d,.]*\s*(?:g|그램)\b|(?:정확(?:히|한)?|음식별|끼니별)[^,.!?;\n]{0,20}(?:g|그램))",
        re.IGNORECASE,
    ),
    "fasting_or_meal_skipping": re.compile(
        r"(?:굶|금식|단식|끼니\s*(?:를\s*)?거르|(?:아침|점심|저녁)\s*(?:은|을|는)?\s*(?:안\s*먹|먹지\s*않)|하루\s*(?:한|1)\s*끼)",
        re.IGNORECASE,
    ),
}


def _resolve_persona(
    persona_override: str | None,
    profile_persona: str | None,
) -> tuple[str, str, str | None]:
    """요청 페르소나를 안전하게 해석하고 실제 출처를 함께 반환한다."""
    raw_override = persona_override.strip() if isinstance(persona_override, str) else None
    if raw_override:
        normalized_override = _PERSONA_ALIASES.get(
            raw_override.casefold(), raw_override)
        if normalized_override in {"천사", "악마", "코치", "현실파이터"}:
            return normalized_override, "request_override", None
        override_status = "invalid_ignored"
    elif persona_override is not None:
        override_status = "blank_ignored"
    else:
        override_status = None

    normalized_profile = normalize_persona(profile_persona) if profile_persona else None
    if profile_persona and normalized_profile == profile_persona:
        return normalized_profile, "profile", override_status
    return DEFAULT_PERSONA, "default", override_status


def _sanitize_meal_preferences(
    preferences: str | None,
) -> tuple[str | None, list[str]]:
    """음식 취향은 보존하고 수치 처방·금식 조건은 계획 입력에서 제외한다."""
    if not isinstance(preferences, str) or not preferences.strip():
        return None, []

    # 위험 조건 앞에서 절을 나눠, 같은 문장에 적힌 앞쪽 음식 취향도 보존한다.
    expanded = re.sub(
        r"\s+(?=(?:하루|매일|음식별|끼니별|아침|점심|저녁)[^,.!?;\n]{0,30}"
        r"(?:\d|kcal|cal|칼로리|그램|\bg\b|굶|금식|단식|안\s*먹|먹지\s*않|거르))",
        ". ",
        preferences.strip(),
        flags=re.IGNORECASE,
    )
    clauses = [
        clause.strip(" \t-:")
        for clause in re.split(r"[,.!?;\n]+", expanded)
        if clause.strip(" \t-:")
    ]
    safe_clauses: list[str] = []
    rejected: list[str] = []
    for clause in clauses:
        # 위험 조건이 먼저 나온 절만 더 잘게 나눠 뒤의 음식 취향을 살린다.
        candidates = [clause]
        if any(pattern.search(clause) for pattern in _UNSAFE_PREFERENCE_PATTERNS.values()):
            candidates = re.split(
                r"(?:먹고|하고)\s+(?=[가-힣A-Za-z][^,.!?;\n]{0,40}"
                r"(?:좋아|싫어|알레르기|못\s*먹))",
                clause,
            )
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue
            matched_categories = [
                category
                for category, pattern in _UNSAFE_PREFERENCE_PATTERNS.items()
                if pattern.search(candidate)
            ]
            if matched_categories:
                rejected.extend(matched_categories)
            else:
                safe_clauses.append(candidate)

    return ", ".join(safe_clauses) or None, list(dict.fromkeys(rejected))


def generate_meal_plan(user_id: str, goal_override: str | None = None,
                       preferences: str | None = None,
                       schedule: list[str] | None = None,
                       persona_override: str | None = None) -> dict:
    """질적 식단 가이드를 끼니별로 구성하고, 톡캘린더 알림 이벤트를 만든다.

    schedule: 끼니 시간대 예 ["08:00","12:30","19:00"]
    반환: {meals[{time, guide}], calendar_events[], note}
    능동 푸시 불가 → calendar_events를 native 톡캘린더에 등록해 알림 우회.
    """
    schedule = schedule or ["08:00", "12:30", "19:00"]
    profile = _profile(user_id)
    profile_goal = profile.get("goal") if profile else None
    profile_persona = profile.get("persona") if profile else None
    goal = normalize_goal(goal_override) or normalize_goal(profile_goal)
    persona, persona_source, persona_override_status = _resolve_persona(
        persona_override, profile_persona)
    goal_label = goal or "유지"
    safe_preferences, rejected_preferences = _sanitize_meal_preferences(preferences)

    meal_options = load_active_meal_options()
    meal_plan = build_meal_plan(
        goal_label,
        meal_types=[MEAL_TYPES[index % len(MEAL_TYPES)] for index in range(len(schedule))],
        preferences=safe_preferences,
        options=meal_options,
    )
    meals = []
    for index, (time, selected) in enumerate(zip(schedule, meal_plan["meals"])):
        base_guide = _format_meal_selection(_meal_name(index), selected)
        meals.append({
            "time": time,
            "meal_name": _meal_name(index),
            "option_id": selected["option_id"],
            "option_name": selected["name"],
            "components": selected["components"],
            "balance_axes": selected["balance_axes"],
            "matched_preferences": selected["matched_preferences"],
            "selection_reason": selected["selection_reason"],
            "allergens": selected["allergens"],
            "dietary_patterns": selected["dietary_patterns"],
            "protein_families": selected["protein_families"],
            "whole_grain": selected["whole_grain"],
            "micronutrient_focus": selected["micronutrient_focus"],
            "training_contexts": selected["training_contexts"],
            "digestibility": selected["digestibility"],
            "recovery_roles": selected["recovery_roles"],
            "evidence_source_ids": selected["evidence_source_ids"],
            "nutrition_verified": selected["nutrition_verified"],
            "review_status": selected["review_status"],
            "base_guide": base_guide,
            "guide": apply_persona(base_guide, persona),
        })

    calendar_events = [
        f"{time} 식사 리마인드: {_meal_name(index)} 균형 챙기기"
        for index, time in enumerate(schedule)
    ]

    preference_guardrail_note = (
        "정확한 칼로리·그램 제한이나 끼니를 거르는 조건은 식단 계획에 반영하지 않았어요."
        if rejected_preferences else None
    )
    base_note = f"{goal_label} 목표에 맞춰 정밀 수치보다 끼니별 균형을 우선으로 잡았어요."
    preference_application_note = None
    if safe_preferences:
        preference_application_note = (
            "말해준 선호와 제외 조건은 실제 메뉴 선택에 반영했어요. "
            "같은 안내를 끼니마다 반복하지 않고 메뉴 구성으로 보여드릴게요."
        )
        base_note = f"{base_note} {preference_application_note}"
    if preference_guardrail_note:
        base_note = f"{base_note} {preference_guardrail_note}"
    note = apply_persona(base_note, persona)
    return {
        "meals": meals,
        "calendar_events": calendar_events,
        "persona": persona,
        "persona_source": persona_source,
        "persona_override_status": persona_override_status,
        "note": note,
        "base_note": base_note,
        "accepted_preferences": safe_preferences,
        "preference_profile": meal_plan["preference_profile"],
        "preference_application_note": preference_application_note,
        "goal_focus": meal_plan["goal_focus"],
        "professional_principles": meal_plan["professional_principles"],
        "meal_catalog_source": "isolated_meal_database",
        "meal_catalog_size": len(meal_options),
        "rejected_preference_categories": rejected_preferences,
        "preference_guardrail_applied": bool(rejected_preferences),
        "preference_guardrail_note": preference_guardrail_note,
        **persona_response_fields(
            persona, base_note, note, fallback_field="note"),
    }


def get_recommendation(
    user_id: str,
    persona_override: str | None = None,
    goal_override: str | None = None,
    current_context: dict | None = None,
) -> dict:
    """식단·추세·방향성을 종합한 질적 코칭 한 마디.

    입력받은 현재 수치 맥락이 있으면 DB 기록보다 우선 평가하고,
    없으면 analyze_trend 결과 + 최근 로그를 묶어 다음 행동을 제안한다.
    """
    profile = _profile(user_id)
    profile_goal = profile.get("goal") if profile else None
    profile_persona = profile.get("persona") if profile else None
    goal = normalize_goal(goal_override) or normalize_goal(profile_goal) or "유지"
    persona, persona_source, persona_override_status = _resolve_persona(
        persona_override, profile_persona)
    trends = {
        "weight": analyze_trend(user_id, "weight", 30),
        "inbody": analyze_trend(user_id, "inbody", 60),
        "meal": analyze_trend(user_id, "meal", 14),
    }

    evaluation = _evaluate_current_context(goal, current_context)
    if evaluation:
        recommendation = evaluation["message"]
    elif trends["meal"]["flag"] in {"insufficient_data", "low_meal_logging"}:
        recommendation = "먼저 식단 기록을 조금 더 쌓아봐요. 기록이 생기면 몸 변화와 같이 묶어서 조정할 수 있어요."
    elif goal == "증량" and trends["weight"]["direction"] == "down":
        recommendation = "증량 목표인데 체중이 내려가는 흐름이에요. 다음 며칠은 끼니를 거르지 말고 단백질과 탄수화물 구성을 안정적으로 가져가봐요."
    elif goal == "감량" and trends["weight"]["direction"] == "up":
        recommendation = "감량 목표 대비 체중이 오르는 흐름이에요. 제한을 세게 걸기보다 간식과 야식 빈도부터 점검해봐요."
    elif trends["inbody"]["direction"] == "down":
        recommendation = "몸 데이터 흐름이 살짝 아쉬워요. 회복, 단백질, 수면을 먼저 챙기고 식사는 너무 빡빡하게 줄이지 않는 쪽이 좋아요."
    elif trends["meal"]["direction"] == "up":
        recommendation = "식단 균형이 좋아지는 흐름이에요. 지금처럼 단백질, 채소, 탄수화물 축을 유지하면서 운동 기록과 같이 보겠습니다."
    else:
        recommendation = "큰 방향은 안정적이에요. 다음 기록에서는 부족한 식사 축 하나만 보완해서 몸 변화와 같이 확인해봐요."

    rendered_recommendation = apply_persona(recommendation, persona)
    return {
        "recommendation": rendered_recommendation,
        "base_recommendation": recommendation,
        "based_on": [
            {"metric": metric, **_compact_trend_result(result)}
            for metric, result in trends.items()
        ],
        "evaluation": evaluation,
        "persona": persona,
        "persona_source": persona_source,
        "persona_override_status": persona_override_status,
        "goal": goal,
        "goal_source": "request_override" if goal_override else "profile_or_default",
        "current_context_used": bool(current_context),
        **persona_response_fields(
            persona, recommendation, rendered_recommendation,
            fallback_field="recommendation"),
        "tone_applied": True,
    }


def suggest_meal_adjustment(
    user_id: str,
    current_meal_text: str | None = None,
    meal_time: str | None = None,
    goal_override: str | None = None,
    current_context: dict | None = None,
    persona_override: str | None = None,
) -> dict:
    """현재 식사·몸 정보·운동량·최근 식단 패턴을 묶어 질적 식단 조정을 제안한다.

    BMI는 키/몸무게가 있을 때 참고 신호로만 쓰며, 칼로리/그램 처방은 하지 않는다.
    """
    profile = _profile(user_id)
    profile_goal = profile.get("goal") if profile else None
    profile_persona = profile.get("persona") if profile else None
    goal = normalize_goal(goal_override) or normalize_goal(profile_goal) or "유지"
    persona, persona_source, persona_override_status = _resolve_persona(
        persona_override, profile_persona)
    body_context = _body_context(user_id, current_context)
    workout_context = _workout_context(user_id, current_context)
    meal_pattern = _recent_meal_pattern(user_id)
    recent_classifications = meal_pattern.get("recent_classifications", [])
    current_meal = (
        classify_meal_text(
            current_meal_text,
            meal_time=meal_time,
            recent_classifications=recent_classifications,
        )
        if current_meal_text is not None
        else None
    )
    public_meal_pattern = {
        key: value
        for key, value in meal_pattern.items()
        if key != "recent_classifications"
    }

    base_recommendation = _meal_adjustment_message(
        goal=goal,
        current_meal=current_meal,
        body_context=body_context,
        workout_context=workout_context,
        meal_pattern=public_meal_pattern,
        meal_time=meal_time,
    )
    recommendation = apply_persona(base_recommendation, persona)
    return {
        "recommendation": recommendation,
        "base_recommendation": base_recommendation,
        "persona": persona,
        "persona_source": persona_source,
        "persona_override_status": persona_override_status,
        "goal": goal,
        "meal_time": meal_time,
        "current_meal_text": current_meal_text,
        "current_meal": current_meal,
        "body_context": body_context,
        "workout_context": workout_context,
        "meal_pattern": public_meal_pattern,
        **persona_response_fields(
            persona, base_recommendation, recommendation,
            fallback_field="recommendation"),
    }


def _goal(user_id: str) -> str | None:
    profile = _profile(user_id)
    return profile.get("goal") if profile else None


def _compact_trend_result(result: dict) -> dict:
    return {
        key: value
        for key, value in result.items()
        if key not in {
            "assistant_message",
            "display_text",
            "message",
            "summary",
            "base_summary",
            "persona",
            "base_message",
            "persona_context",
            "rewrite_instruction",
            "response_meta",
            "user_response_contract",
        }
    }


def _context_number(context: dict | None, *keys: str) -> float | None:
    if not context:
        return None
    for key in keys:
        value = context.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                continue
    return None


def _context_text(context: dict | None, *keys: str) -> str | None:
    if not context:
        return None
    for key in keys:
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _evaluate_current_context(goal: str, current_context: dict | None) -> dict | None:
    if not current_context:
        return None

    weekly_sessions = _context_number(
        current_context, "weekly_sessions", "workout_count", "weekly_workouts")
    target_sessions = _context_number(
        current_context, "target_weekly_sessions", "available_days", "target_workouts")
    fatigue = _context_text(current_context, "fatigue", "recent_fatigue", "fatigue_level")
    sleep = _context_text(current_context, "sleep_quality", "sleep")
    session_minutes = _context_number(
        current_context, "session_minutes", "workout_minutes", "avg_session_minutes")

    values = {
        "weekly_sessions": weekly_sessions,
        "target_weekly_sessions": target_sessions,
        "session_minutes": session_minutes,
        "fatigue": fatigue,
        "sleep_quality": sleep,
    }
    values = {key: value for key, value in values.items() if value is not None}

    high_fatigue = fatigue in {"높음", "high", "bad", "나쁨", "피곤", "피로 높음"}
    low_sleep = sleep in {"낮음", "low", "bad", "나쁨", "부족"}
    if weekly_sessions is not None and weekly_sessions >= 4 and (high_fatigue or low_sleep):
        return {
            "status": "needs_recovery",
            "basis": "current_context",
            "values": values,
            "message": "이번 입력 기준으로 운동 빈도는 높은 편인데 피로나 수면 신호가 좋지 않아요. 지금은 운동을 더 늘리기보다 회복, 수면, 강도 조절을 먼저 잡는 게 좋아요.",
        }

    if (
        weekly_sessions is not None
        and target_sessions is not None
        and weekly_sessions + 1 < target_sessions
    ):
        return {
            "status": "below_frequency_target",
            "basis": "current_context",
            "values": values,
            "message": "이번 입력 기준으로 목표 운동 횟수보다 실제 운동 횟수가 부족해요. 무리해서 한 번에 몰아 하기보다 다음 주에는 가능한 요일을 먼저 고정해 빈도부터 회복해봐요.",
        }

    if (
        weekly_sessions is not None
        and target_sessions is not None
        and weekly_sessions >= target_sessions
        and goal == "증량"
    ):
        return {
            "status": "frequency_on_track_for_gain",
            "basis": "current_context",
            "values": values,
            "message": "이번 입력 기준으로 증량 목표에 필요한 운동 빈도는 잘 맞고 있어요. 이제는 세트 수행 품질, 점진적 과부하, 끼니 누락 방지를 같이 챙기면 좋아요.",
        }

    if session_minutes is not None and session_minutes < 30:
        return {
            "status": "short_sessions",
            "basis": "current_context",
            "values": values,
            "message": "이번 입력 기준으로 세션 시간이 짧은 편이에요. 운동 시간을 크게 늘리기 어렵다면 핵심 복합 동작과 기록 유지에 우선순위를 두는 게 좋아요.",
        }

    if values:
        return {
            "status": "context_checked",
            "basis": "current_context",
            "values": values,
            "message": "이번에 입력한 수치 기준으로 큰 위험 신호는 뚜렷하지 않아요. 현재 패턴을 유지하면서 부족한 축 하나만 정해 다음 기록에서 같이 확인해봐요.",
        }
    return None


def _profile(user_id: str):
    session = SessionLocal()
    try:
        u = session.get(User, user_id)
        if not u:
            return None
        return {
            "goal": u.goal,
            "persona": u.persona,
        }
    finally:
        session.close()


def _latest_weight(session, user_id: str) -> float | None:
    row = (
        session.query(WeightLog)
        .filter(WeightLog.user_id == user_id)
        .order_by(WeightLog.date.desc(), WeightLog.id.desc())
        .first()
    )
    return row.weight if row else None


def _latest_inbody_weight(session, user_id: str) -> float | None:
    row = (
        session.query(InbodyLog)
        .filter(InbodyLog.user_id == user_id, InbodyLog.weight.isnot(None))
        .order_by(InbodyLog.measured_date.desc(), InbodyLog.id.desc())
        .first()
    )
    return row.weight if row else None


def _bmi_band(bmi: float | None) -> str | None:
    if bmi is None:
        return None
    if bmi < 18.5:
        return "low"
    if bmi < 23:
        return "normal"
    if bmi < 25:
        return "normal_high"
    return "high"


def _body_context(user_id: str, current_context: dict | None = None) -> dict:
    height_cm = _context_number(current_context, "height_cm", "height")
    weight_kg = _context_number(current_context, "weight_kg", "weight")

    session = SessionLocal()
    try:
        if weight_kg is None:
            weight_kg = _latest_inbody_weight(session, user_id)
        if weight_kg is None:
            weight_kg = _latest_weight(session, user_id)
    finally:
        session.close()

    bmi = None
    if height_cm and weight_kg:
        height_m = height_cm / 100
        if height_m > 0:
            bmi = round(weight_kg / (height_m * height_m), 1)

    return {
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "bmi": bmi,
        "bmi_band": _bmi_band(bmi),
        "bmi_available": bmi is not None,
        "bmi_note": "BMI는 식단 조정의 참고 신호이며 진단이나 처방 기준이 아닙니다.",
    }


def _start_of_day(day) -> datetime:
    return datetime.combine(day, time.min)


def _workout_context(user_id: str, current_context: dict | None = None) -> dict:
    weekly_workouts = _context_number(
        current_context, "weekly_sessions", "workout_count", "weekly_workouts")
    if weekly_workouts is None:
        since = datetime.now().date() - timedelta(days=7)
        session = SessionLocal()
        try:
            weekly_workouts = (
                session.query(WorkoutLog)
                .filter(WorkoutLog.user_id == user_id,
                        WorkoutLog.date >= since)
                .count()
            )
        finally:
            session.close()

    volume_trend = analyze_trend(user_id, "volume", 14)
    return {
        "weekly_workouts": int(weekly_workouts or 0),
        "volume_direction": volume_trend.get("direction"),
        "volume_flag": volume_trend.get("flag"),
    }


def _recent_meal_pattern(user_id: str, period_days: int = 14) -> dict:
    since = _start_of_day(datetime.now().date() - timedelta(days=period_days))
    session = SessionLocal()
    try:
        logs = (
            session.query(MealLog)
            .filter(MealLog.user_id == user_id, MealLog.logged_at >= since)
            .order_by(MealLog.logged_at.desc(), MealLog.id.desc())
            .limit(21)
            .all()
        )
    finally:
        session.close()

    classifications = [
        classify_meal_text(log.meal_text or "")
        for log in logs
    ]
    summary = summarize_meal_classifications(classifications)
    summary["recent_classifications"] = classifications[:8]
    return summary


def _missing_axes(current_meal: dict | None, meal_pattern: dict) -> list[str]:
    axes = []
    if current_meal:
        axes.extend(current_meal.get("missing_axes", []))
    axes.extend(meal_pattern.get("common_missing_axes", []))
    return list(dict.fromkeys(axes))


def _risk_flags(current_meal: dict | None, meal_pattern: dict) -> list[str]:
    risks = []
    if current_meal:
        risks.extend(current_meal.get("risk_flags", []))
    risks.extend(meal_pattern.get("frequent_risk_flags", []))
    return list(dict.fromkeys(risks))


def _meal_adjustment_message(
    goal: str,
    current_meal: dict | None,
    body_context: dict,
    workout_context: dict,
    meal_pattern: dict,
    meal_time: str | None = None,
) -> str:
    missing = _missing_axes(current_meal, meal_pattern)
    risks = _risk_flags(current_meal, meal_pattern)
    weekly_workouts = workout_context.get("weekly_workouts", 0)
    bmi_band = body_context.get("bmi_band")
    bmi_clause = " BMI는 참고만 하고,"
    meal_clause = f"{meal_time} 기준으로 " if meal_time else ""

    if current_meal and current_meal.get("balance_flag") == "skipped_meal":
        return (
            f"{meal_clause}끼니를 거른 신호가 보여요.{bmi_clause} 다음 식사는 "
            "몰아 먹기보다 단백질과 탄수화물을 같이 넣어 회복부터 안정시키면 좋아요."
        )
    if current_meal and current_meal.get("needs_follow_up"):
        question = (current_meal.get("follow_up_questions") or ["구성을 조금만 더 알려주세요."])[0]
        return (
            f"{meal_clause}이번 식단 기록은 조금 넓게 들어와서 단정하기 어려워요.{bmi_clause} "
            f"{question} 그 답을 기준으로 다음 끼니 조정을 더 정확히 잡을게요."
        )
    if "protein" in missing:
        return (
            f"{meal_clause}최근 식단에서 단백질 축이 자주 비어요.{bmi_clause} "
            "운동 회복을 생각하면 다음 끼니는 고기, 생선, 계란, 두부 같은 단백질을 먼저 정해봐요."
        )
    if "vegetable" in missing:
        return (
            f"{meal_clause}에너지원은 보이지만 채소 축이 약해요.{bmi_clause} "
            "다음 끼니엔 샐러드, 나물, 김치, 쌈채소 중 하나만 붙여도 균형이 좋아져요."
        )
    if "carb" in missing and weekly_workouts >= 3:
        return (
            f"{meal_clause}운동량이 있는 편인데 탄수화물 축이 자주 빠져요.{bmi_clause} "
            "운동 전후 식사는 밥, 고구마, 오트처럼 에너지원을 완전히 빼지 않는 쪽이 좋아요."
        )
    if goal == "증량" and weekly_workouts >= 3:
        return (
            f"{meal_clause}증량 목표와 운동 빈도는 연결이 좋아요.{bmi_clause} "
            "끼니를 거르지 말고 단백질과 탄수화물을 같은 끼니 안에 안정적으로 묶어가면 됩니다."
        )
    if goal == "감량" and risks:
        return (
            f"{meal_clause}감량 목표라면 제한을 세게 걸기보다 달달한 음료, 디저트, 튀김 같은 "
            f"곁가지 빈도부터 줄이는 게 좋아요.{bmi_clause} 기본 끼니 균형은 유지해요."
        )
    if bmi_band in {"normal_high", "high"} and goal != "증량" and risks:
        return (
            f"{meal_clause}현재 몸 정보 기준으로는 곁가지 빈도 조절이 우선이에요.{bmi_clause} "
            "식사량을 과하게 줄이기보다 음료·간식·튀김 빈도를 먼저 낮춰봐요."
        )
    return (
        f"{meal_clause}큰 방향은 괜찮아요.{bmi_clause} 다음 기록에서는 단백질, 채소, "
        "탄수화물 세 축이 한 끼 안에 보이는지만 확인해봐요."
    )


def _meal_name(index: int) -> str:
    names = ["아침", "점심", "저녁", "간식"]
    return names[index] if index < len(names) else f"식사 {index + 1}"


def _format_meal_selection(meal_name: str, selected: dict) -> str:
    """선택된 식단을 균형 축이 보이는 자연스러운 질적 가이드로 만든다."""
    component_labels = {
        "protein": "단백질",
        "carbohydrate": "복합 탄수화물",
        "produce": "채소·과일",
        "healthy_fat": "건강한 지방",
    }
    components = ", ".join(
        f"{component_labels.get(axis, axis)}: {food}"
        for axis, food in selected["components"].items()
    )
    return (
        f"{meal_name}: {selected['name']} — {components}로 구성해요. "
        f"선정 기준은 {selected['selection_reason']}입니다."
    )
