"""Persona tone helpers.

Persona changes wording only. It must not loosen nutrition, safety, or
training guardrails.
"""
from db.session import SessionLocal
from db.models import User

DEFAULT_PERSONA = "코치"


def get_persona(user_id: str) -> str:
    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        return user.persona if user and user.persona else DEFAULT_PERSONA
    finally:
        session.close()


def apply_persona(text: str, persona: str | None) -> str:
    if not text:
        return text

    if persona == "악마":
        return f"악마모드: {text} 변명은 여기까지. 대충 넘기면 몸은 바로 티 냅니다. 지금 할 것부터 끝내요."
    if persona == "천사":
        return f"천사모드: {text} 천천히 해도 괜찮으니, 오늘 한 가지만 챙겨봐요."
    if persona == "현실파이터":
        return f"현실파이터: {text} 완벽 말고, 지금 가능한 선택부터 갑시다."
    return f"코치모드: {text} 운동 많이 될 거야. 스트레스 조금 받을 거야. 그래도 오늘 할 거 하면 몸은 좋아질 거야."
