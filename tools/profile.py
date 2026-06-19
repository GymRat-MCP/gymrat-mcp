"""프로필 툴 — 매 세션 '나를 기억함'의 핵심"""
from db.session import SessionLocal
from db.models import User

VALID_PERSONAS = {"천사", "악마", "코치", "현실파이터"}


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
) -> dict:
    """프로필을 생성/갱신한다. 전달된 필드만 업데이트(부분 갱신)."""
    if persona is not None and persona not in VALID_PERSONAS:
        return {"updated": False, "error": f"persona must be one of {VALID_PERSONAS}"}

    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        if not user:
            user = User(id=user_id)
            session.add(user)

        if goal is not None:
            user.goal = goal
        if experience is not None:
            user.experience = experience
        if injuries is not None:
            user.injuries = injuries
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
