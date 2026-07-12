"""프로필 툴 — 매 세션 '나를 기억함'의 핵심

호스트 LLM이 goal/experience를 영문·변형값("중급자", "bulk")으로 보낼 수 있으므로
저장 시점에 한글 정규값으로 통일한다(= 모든 소비자가 깨끗한 값을 받음).
"""
from db.session import SessionLocal
from db.models import User

VALID_PERSONAS = {"천사", "악마", "코치", "현실파이터"}
VALID_SPLIT_STYLES = {"자동", "PPL", "부위별"}

# 경력 정규화: 표준값 "초보|중급|고급"
_EXPERIENCE_BEGINNER = ("beginner", "novice", "newbie")
_EXPERIENCE_INTERMEDIATE = ("intermediate",)
_EXPERIENCE_ADVANCED = ("advanced", "expert", "pro")

# 목표 정규화: 표준값 "증량|감량|유지"
_GOAL_BULK = ("증량", "벌크", "근비대", "근성장", "근육", "bulk", "gain",
              "muscle", "hypertrophy", "mass")
_GOAL_CUT = ("감량", "다이어트", "체지방", "컷", "cut", "loss", "lose",
             "lean", "fat")
_GOAL_MAINTAIN = ("유지", "메인터넌스", "maintain", "maintenance")


def normalize_experience(value: str | None) -> str | None:
    """'중급자', 'Intermediate' 등을 표준 '초보|중급|고급'으로 통일."""
    if not value:
        return value
    raw = value.strip()
    low = raw.lower()
    if raw.startswith(("초보", "입문")) or low in _EXPERIENCE_BEGINNER:
        return "초보"
    if raw.startswith("중급") or low in _EXPERIENCE_INTERMEDIATE:
        return "중급"
    if raw.startswith(("고급", "상급")) or low in _EXPERIENCE_ADVANCED:
        return "고급"
    return raw  # 미인식 값은 그대로 보존(파괴적 손실 금지)


def normalize_goal(value: str | None) -> str | None:
    """'다이어트', 'bulk' 등을 표준 '증량|감량|유지'로 통일."""
    if not value:
        return value
    raw = value.strip()
    low = raw.lower()
    if any(k in raw or k in low for k in _GOAL_BULK):
        return "증량"
    if any(k in raw or k in low for k in _GOAL_CUT):
        return "감량"
    if any(k in raw or k in low for k in _GOAL_MAINTAIN):
        return "유지"
    return raw


def get_profile(user_id: str) -> dict:
    """저장된 사용자 프로필을 반환한다. 없으면 빈 프로필."""
    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        if not user:
            return {"exists": False, "user_id": user_id}
        return {
            "exists": True,
            "user_id": user.id,
            "goal": user.goal,
            "experience": user.experience,
            "injuries": user.injuries,
            "available_equipment": user.available_equipment,
            "disliked_exercises": user.disliked_exercises,
            "training_days": user.training_days,
            "split_style": user.split_style,
            "custom_split": user.custom_split,
            "persona": user.persona,
            "summary_context": user.summary_context,
        }
    finally:
        session.close()


def update_profile(
    user_id: str,
    goal: str | None = None,
    experience: str | None = None,
    injuries: str | None = None,
    persona: str | None = None,
    summary_context: str | None = None,
    available_equipment: str | None = None,
    disliked_exercises: str | None = None,
    training_days: int | None = None,
    split_style: str | None = None,
) -> dict:
    """프로필을 생성/갱신한다. 전달된 필드만 업데이트(부분 갱신)."""
    if persona is not None and persona not in VALID_PERSONAS:
        return {"updated": False, "error": f"persona must be one of {VALID_PERSONAS}"}
    if split_style is not None and split_style not in VALID_SPLIT_STYLES:
        return {"updated": False,
                "error": f"split_style must be one of {VALID_SPLIT_STYLES}"}
    if training_days is not None:
        training_days = max(1, min(6, int(training_days)))   # 1~6 클램프

    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        if not user:
            user = User(id=user_id)
            session.add(user)

        if goal is not None:
            user.goal = normalize_goal(goal)
        if experience is not None:
            user.experience = normalize_experience(experience)
        if injuries is not None:
            user.injuries = injuries
        if available_equipment is not None:
            user.available_equipment = available_equipment
        if disliked_exercises is not None:
            user.disliked_exercises = disliked_exercises
        if training_days is not None:
            user.training_days = training_days
        if split_style is not None:
            user.split_style = split_style
        if persona is not None:
            user.persona = persona
        if summary_context is not None:
            user.summary_context = summary_context

        session.commit()
        return {"updated": True, "user_id": user_id}
    except Exception as e:
        session.rollback()
        return {"updated": False, "error": str(e)}
    finally:
        session.close()
