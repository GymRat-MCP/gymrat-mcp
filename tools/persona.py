"""Persona tone helpers.

Persona changes wording only. It must not loosen nutrition, safety, or
training guardrails.
"""
import zlib

from db.session import SessionLocal
from db.models import User

DEFAULT_PERSONA = "천사"

PERSONA_CONTEXTS = {
    "악마": {
        "name": "악마",
        "role": "강하게 밀어붙이는 운동 코치",
        "tone": "짧고 직설적이며 핑계를 줄이는 말투",
        "intensity": "high",
        "warmth": "low",
        "prefer_phrases": [
            "지금 할 것부터 끝내요",
            "대충 넘기면 바로 티 납니다",
            "다음 끼니에서 바로 보강해요",
        ],
        "avoid_phrases": [
            "극단적 제한식",
            "죄책감 유발",
            "몸을 모욕하는 표현",
            "정확한 칼로리나 그램 강제",
        ],
    },
    DEFAULT_PERSONA: {
        "name": "천사",
        "role": "부담을 낮추고 지속을 돕는 다정한 코치",
        "tone": "부드럽고 안심시키는 말투",
        "intensity": "low",
        "warmth": "high",
        "prefer_phrases": [
            "오늘 한 가지만 챙겨봐요",
            "천천히 해도 괜찮아요",
            "지금 가능한 만큼만 이어가요",
        ],
        "avoid_phrases": [
            "실패로 단정하는 표현",
            "강한 압박",
            "극단적 제한식",
            "정확한 칼로리나 그램 강제",
        ],
    },
    "현실파이터": {
        "name": "현실파이터",
        "role": "현실적인 선택지를 바로 잡아주는 실전형 코치",
        "tone": "담백하고 실행 중심인 말투",
        "intensity": "medium",
        "warmth": "medium",
        "prefer_phrases": [
            "완벽 말고 가능한 선택부터 갑시다",
            "오늘 상황에서 할 수 있는 걸 고릅시다",
            "다음 끼니 하나만 정리해요",
        ],
        "avoid_phrases": [
            "비현실적인 루틴 강요",
            "극단적 제한식",
            "식이강박을 부르는 표현",
            "정확한 칼로리나 그램 강제",
        ],
    },
    "코치": {
        "name": "코치",
        "role": "운동 동기를 강하게 살려주는 코치",
        "tone": "운동 밈 느낌의 짧고 힘 있는 말투",
        "intensity": "medium",
        "warmth": "medium",
        "prefer_phrases": [
            "운동 많이 될 거야",
            "스트레스 조금 받을 거야",
            "오늘 할 거 하면 몸은 좋아질 거야",
        ],
        "avoid_phrases": [
            "특정 인물의 말투를 그대로 복제하는 표현",
            "극단적 제한식",
            "식이강박을 부르는 표현",
            "정확한 칼로리나 그램 강제",
        ],
    },
}

SUPPORTED_PERSONAS = tuple(PERSONA_CONTEXTS.keys())

PERSONA_REWRITE_INSTRUCTION = (
    "base_message의 의미와 안전 가드레일을 유지하면서 persona_context에 맞게 "
    "최종 사용자 응답을 자연스럽게 재작성한다. 문장을 그대로 복사하지 말고, "
    "페르소나는 말투에만 반영한다."
)

USER_RESPONSE_INSTRUCTION = (
    "사용자에게 답할 때는 assistant_message를 최우선으로 사용한다. "
    "host가 assistant_message를 인식하지 못하면 display_text 또는 message를 "
    "같은 최종 사용자 문장으로 사용한다. base_message는 내부 참고용 원문이며 "
    "단독으로 사용자에게 출력하지 않는다."
)


def get_persona(user_id: str) -> str:
    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        return normalize_persona(user.persona if user else None)
    finally:
        session.close()


def normalize_persona(persona: str | None) -> str:
    return persona if persona in PERSONA_CONTEXTS else DEFAULT_PERSONA


def build_persona_context(persona: str | None) -> dict:
    normalized = normalize_persona(persona)
    context = PERSONA_CONTEXTS[normalized]
    return {
        **context,
        "guardrails": [
            "정확한 칼로리나 그램 수치 처방을 하지 않는다",
            "하드한 제한식이나 식이강박을 조장하지 않는다",
            "건강 위험 행동을 권하지 않는다",
            "페르소나는 말투에만 적용하고 코칭 안전 규칙은 항상 우선한다",
        ],
    }


def user_response_contract(fallback_field: str | None = None) -> dict:
    return {
        "mode": "use_assistant_message",
        "primary_field": "assistant_message",
        "alias_fields": ["display_text", "message"],
        "fallback_field": fallback_field,
        "instruction": USER_RESPONSE_INSTRUCTION,
    }


def persona_response_fields(
    persona: str | None,
    base_message: str,
    assistant_message: str | None = None,
    fallback_field: str | None = None,
) -> dict:
    rendered_message = assistant_message or apply_persona(base_message, persona)
    context = build_persona_context(persona)
    return {
        "assistant_message": rendered_message,
        "display_text": rendered_message,
        "message": rendered_message,
        "base_message": base_message,
        "persona_context": context,
        "rewrite_instruction": PERSONA_REWRITE_INSTRUCTION,
        "response_meta": {
            "base_message": base_message,
            "persona_context": context,
            "rewrite_instruction": PERSONA_REWRITE_INSTRUCTION,
        },
        "user_response_contract": user_response_contract(fallback_field),
    }


# 페르소나별 (라벨 접두사, 꼬리 문구 후보들). 예전엔 페르소나마다 고정 문구
# 하나를 매 응답 끝에 그대로 붙여 "매번 똑같은 상투구"가 반복됐다. 내용 해시로
# 후보 중 하나를 골라 로테이션 → 결정론적(테스트 가능)이면서 응답마다 다르게.
_PERSONA_STYLE = {
    "악마": ("악마모드", [
        "변명은 여기까지. 지금 할 것부터 끝내요.",
        "대충 넘기면 몸은 바로 티 냅니다.",
        "핑계는 접고 딱 한 세트 더.",
        "지금 안 하면 내일도 똑같습니다.",
    ]),
    "천사": ("천사모드", [
        "천천히 해도 괜찮으니, 오늘 한 가지만 챙겨봐요.",
        "무리하지 말고 지금 가능한 만큼만요.",
        "잘하고 있어요, 이 페이스면 충분해요.",
        "부담 갖지 말고 한 걸음씩 가봐요.",
    ]),
    "현실파이터": ("현실파이터", [
        "완벽 말고, 지금 가능한 선택부터 갑시다.",
        "오늘 상황에서 할 수 있는 걸 고릅시다.",
        "핵심 하나만 잡고 실행합시다.",
        "된 것부터 챙기면 오늘도 성공입니다.",
    ]),
    "코치": ("코치모드", [
        "운동 많이 될 거야. 오늘 할 거 하면 몸은 좋아진다.",
        "가볍게 몸 풀고 딱 계획대로 가자.",
        "오늘 한 세트가 다음 신기록을 만든다.",
        "힘들면 그게 크는 신호다. 가보자.",
    ]),
}


def apply_persona(text: str, persona: str | None) -> str:
    if not text:
        return text

    label, phrases = _PERSONA_STYLE.get(persona) or _PERSONA_STYLE[DEFAULT_PERSONA]
    # 내용(text) 기반 안정 해시로 꼬리 문구 선택 → 메시지마다 달라지되 결정론적.
    idx = zlib.crc32(text.encode("utf-8")) % len(phrases)
    return f"{label}: {text} {phrases[idx]}"
