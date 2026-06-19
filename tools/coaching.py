"""식단 플랜 + 전반 코칭

⚠️ 가드레일(중요):
- 정확 칼로리/그램 처방 ❌ → 질적 가이드만 ("아침: 단백질 위주, 계란+오트밀 정도")
- 하드한 제한식 ❌, 식이강박 보호
- 페르소나(천사/악마/코치/현실파이터)는 '말투'만 — 가드레일은 항상 적용
"""
from db.session import SessionLocal
from db.models import User


def generate_meal_plan(user_id: str, goal_override: str | None = None,
                       preferences: str | None = None,
                       schedule: list[str] | None = None) -> dict:
    """질적 식단 가이드를 끼니별로 구성하고, 톡캘린더 알림 이벤트를 만든다.

    schedule: 끼니 시간대 예 ["08:00","12:30","19:00"]
    반환: {meals[{time, guide}], calendar_events[], note}
    능동 푸시 불가 → calendar_events를 native 톡캘린더에 등록해 알림 우회.
    """
    schedule = schedule or ["08:00", "12:30", "19:00"]
    goal = goal_override or _goal(user_id)

    # TODO: goal + preferences 기반 끼니별 질적 가이드 생성 (수치 X)
    meals = [{"time": t, "guide": "TODO: 질적 가이드"} for t in schedule]

    # TODO: 캘린더 등록 문자열 생성 (native 연동 측에서 사용)
    calendar_events = []

    note = "TODO: 페르소나 톤 반영한 한 줄 코멘트"
    return {"meals": meals, "calendar_events": calendar_events, "note": note}


def get_recommendation(user_id: str) -> dict:
    """식단·추세·방향성을 종합한 질적 코칭 한 마디.

    analyze_trend 결과 + 최근 로그를 묶어 '다음에 뭘 하면 좋은지' 제안.
    """
    # TODO: analyze_trend 호출 결과 종합 → 페르소나 톤으로 방향 제안
    return {"recommendation": "TODO: 종합 코칭", "based_on": []}


def _goal(user_id: str) -> str | None:
    session = SessionLocal()
    try:
        u = session.get(User, user_id)
        return u.goal if u else None
    finally:
        session.close()
