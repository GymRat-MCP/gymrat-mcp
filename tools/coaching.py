"""식단 플랜 + 전반 코칭

⚠️ 가드레일(중요):
- 정확 칼로리/그램 처방 ❌ → 질적 가이드만 ("아침: 단백질 위주, 계란+오트밀 정도")
- 하드한 제한식 ❌, 식이강박 보호
- 페르소나(천사/악마/코치/현실파이터)는 '말투'만 — 가드레일은 항상 적용
"""
from datetime import datetime, time, timedelta

from db.session import SessionLocal
from db.models import User, WeightLog, InbodyLog, WorkoutLog, MealLog
from tools.analysis import analyze_trend
from tools.meal_intel import (
    classify_meal_text,
    summarize_meal_classifications,
)
from tools.persona import (
    DEFAULT_PERSONA,
    apply_persona,
    normalize_persona,
    persona_response_fields,
)
from tools.profile import normalize_goal


def generate_meal_plan(user_id: str, goal_override: str | None = None,
                       preferences: str | None = None,
                       schedule: list[str] | None = None) -> dict:
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
    persona = normalize_persona(profile_persona or DEFAULT_PERSONA)
    goal_label = goal or "유지"
    pref_text = f" 선호: {preferences}." if preferences else ""

    guides = _meal_guides(goal_label)
    meals = []
    for index, time in enumerate(schedule):
        base_guide = f"{_meal_name(index)}: {guides[index % len(guides)]}{pref_text}"
        meals.append({
            "time": time,
            "base_guide": base_guide,
            "guide": apply_persona(base_guide, persona),
        })

    calendar_events = [
        f"{time} 식사 리마인드: {_meal_name(index)} 균형 챙기기"
        for index, time in enumerate(schedule)
    ]

    base_note = f"{goal_label} 목표에 맞춰 정밀 수치보다 끼니별 균형을 우선으로 잡았어요."
    note = apply_persona(base_note, persona)
    return {
        "meals": meals,
        "calendar_events": calendar_events,
        "persona": persona,
        "note": note,
        "base_note": base_note,
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
    persona = normalize_persona(persona_override or profile_persona)
    trends = {
        "weight": analyze_trend(user_id, "weight", 30),
        "inbody": analyze_trend(user_id, "inbody", 60),
        "meal": analyze_trend(user_id, "meal", 14),
    }

    evaluation = _evaluate_current_context(goal, current_context)
    if evaluation:
        recommendation = evaluation["message"]
    elif trends["meal"]["flag"] in {"insufficient_data", "low_meal_logging"}:
        recommendation = "먼저 식단 사진 기록을 조금 더 쌓아봐요. 기록이 생기면 몸 변화와 같이 묶어서 조정할 수 있어요."
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
        "persona_source": "request_override" if persona_override else "profile_or_default",
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
) -> dict:
    """현재 식사·몸 정보·운동량·최근 식단 패턴을 묶어 질적 식단 조정을 제안한다.

    BMI는 키/몸무게가 있을 때 참고 신호로만 쓰며, 칼로리/그램 처방은 하지 않는다.
    """
    profile = _profile(user_id)
    profile_goal = profile.get("goal") if profile else None
    profile_persona = profile.get("persona") if profile else None
    goal = normalize_goal(goal_override) or normalize_goal(profile_goal) or "유지"
    persona = normalize_persona(profile_persona or DEFAULT_PERSONA)
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
        classify_meal_text(log.photo_analysis or "")
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


def _meal_guides(goal: str) -> list[str]:
    if goal == "증량":
        return [
            "단백질을 먼저 깔고, 운동 에너지용 탄수화물을 함께 챙겨요.",
            "밥이나 면 같은 주 에너지원을 빼지 말고, 고기·생선·두부류를 곁들여요.",
            "하루 마무리는 과식보다 회복에 초점을 두고 단백질과 소화 편한 탄수화물을 챙겨요.",
        ]
    if goal == "감량":
        return [
            "단백질과 채소를 먼저 채우고, 탄수화물은 활동량에 맞춰 적당히 둬요.",
            "포만감 있는 구성을 우선하고, 소스·튀김·달달한 음료 빈도를 줄여봐요.",
            "늦은 시간엔 과한 제한보다 가벼운 단백질과 채소 중심으로 정리해요.",
        ]
    return [
        "단백질, 채소, 탄수화물이 한 끼 안에 모두 보이게 구성해요.",
        "운동 전후라면 탄수화물을 너무 빼지 말고 회복용 단백질을 같이 챙겨요.",
        "하루 전체 균형을 보고 부족했던 축을 저녁에 보완해요.",
    ]
