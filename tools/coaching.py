"""식단 플랜 + 전반 코칭

⚠️ 가드레일(중요):
- 정확 칼로리/그램 처방 ❌ → 질적 가이드만 ("아침: 단백질 위주, 계란+오트밀 정도")
- 하드한 제한식 ❌, 식이강박 보호
- 페르소나(천사/악마/코치/현실파이터)는 '말투'만 — 가드레일은 항상 적용
"""
from db.session import SessionLocal
from db.models import User
from tools.analysis import analyze_trend
from tools.persona import apply_persona


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
    goal = goal_override or (profile.get("goal") if profile else None)
    persona = (profile.get("persona") if profile else None) or "코치"
    goal_label = goal or "유지"
    pref_text = f" 선호: {preferences}." if preferences else ""

    guides = _meal_guides(goal_label)
    meals = [
        {
            "time": time,
            "guide": apply_persona(
                f"{_meal_name(index)}: {guides[index % len(guides)]}{pref_text}",
                persona,
            ),
        }
        for index, time in enumerate(schedule)
    ]

    calendar_events = [
        f"{time} 식사 리마인드: {_meal_name(index)} 균형 챙기기"
        for index, time in enumerate(schedule)
    ]

    note = apply_persona(
        f"{goal_label} 목표에 맞춰 정밀 수치보다 끼니별 균형을 우선으로 잡았어요.",
        persona,
    )
    return {"meals": meals, "calendar_events": calendar_events, "persona": persona, "note": note}


def get_recommendation(user_id: str) -> dict:
    """식단·추세·방향성을 종합한 질적 코칭 한 마디.

    analyze_trend 결과 + 최근 로그를 묶어 '다음에 뭘 하면 좋은지' 제안.
    """
    profile = _profile(user_id)
    goal = (profile.get("goal") if profile else None) or "유지"
    persona = (profile.get("persona") if profile else None) or "코치"
    trends = {
        "weight": analyze_trend(user_id, "weight", 30),
        "inbody": analyze_trend(user_id, "inbody", 60),
        "meal": analyze_trend(user_id, "meal", 14),
    }

    if trends["meal"]["flag"] in {"insufficient_data", "low_meal_logging"}:
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

    return {
        "recommendation": apply_persona(recommendation, persona),
        "based_on": [
            {"metric": metric, **result}
            for metric, result in trends.items()
        ],
        "persona": persona,
        "tone_applied": True,
    }


def _goal(user_id: str) -> str | None:
    profile = _profile(user_id)
    return profile.get("goal") if profile else None


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
