"""Persona tone helpers.

Persona changes wording only. It must not loosen nutrition, safety, or
training guardrails.
"""
import re

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


_PERSONA_LABELS = {
    "악마": "악마모드",
    "천사": "천사모드",
    "현실파이터": "현실파이터",
    "코치": "코치모드",
}


# 범용 독려 문구가 오히려 안내를 뒤집는 문맥들이다. 예를 들어 회복을 먼저
# 하라는 문장 뒤에 "힘들면 크는 신호"를 붙이면 페르소나가 안전 안내를
# 훼손한다. 이 문맥에서는 본문 말투만 바꾸고 범용 꼬리말은 붙이지 않는다.
_CONTEXT_PATTERNS = {
    "safety": (
        "통증", "부상", "다쳤", "회복", "휴식", "수면", "강도 조절",
        "무게를 낮", "운동을 더 늘리기보다", "중단", "의료", "병원",
        "정확한 칼로리", "그램 제한", "끼니를 거르는", "굶",
    ),
    "error": (
        "오류", "에러", "실패", "저장하지 못", "처리하지 못", "찾을 수 없",
        "유효하지 않", "지원하지 않",
    ),
    "confirmation": (
        "알려주면", "알려주세요", "확인해", "단정하기 어려", "맞나요",
        "있었는지", "더 정확히", "추가로",
    ),
    "status": (
        "첫 인바디 기록", "기록을 저장", "기준점으로 삼", "추세 분석에 반영",
    ),
    "plan": (
        "목표에 맞춰", "식단 계획을", "끼니별 균형을 우선",
    ),
}

_STRUCTURED_PREFIX = re.compile(r"^\s*(?:아침|점심|저녁|간식|운동|세트)\s*:")
_KNOWN_LABELS = tuple(f"{label}:" for label in _PERSONA_LABELS.values())


def _message_context(text: str) -> str:
    """Classify contexts where a generic motivational suffix is inappropriate."""
    if _STRUCTURED_PREFIX.match(text):
        return "structured"
    for context, patterns in _CONTEXT_PATTERNS.items():
        if any(pattern in text for pattern in patterns):
            return context
    if "?" in text or text.rstrip().endswith(("까요?", "나요?", "세요?")):
        return "confirmation"
    return "general"


def _rewrite_tone(text: str, persona: str, context: str) -> str:
    """Apply small, deterministic tone edits without changing factual content.

    This is deliberately conservative: tools own the coaching facts and safety
    decision, while this layer owns sentence cadence and degree of directness.
    """
    replacements = {
        "악마": (
            ("해봐요", "하세요"),
            ("챙겨봐요", "챙기세요"),
            ("챙겨요", "챙기세요"),
            ("보강해요", "보강하세요"),
            ("좋을 것 같아요", "좋습니다"),
            ("좋아요", "좋습니다"),
            ("알려주면", "알려주세요. 그러면"),
        ),
        "천사": (
            ("해야 합니다", "해도 좋아요"),
            ("하세요", "해봐요"),
            ("좋습니다", "좋아요"),
        ),
        "현실파이터": (
            ("챙겨봐요", "챙깁시다"),
            ("챙겨요", "챙깁시다"),
            ("보강해요", "보강합시다"),
            ("보강해봐요", "보강합시다"),
            ("해봐요", "해봅시다"),
            ("좋아요", "좋습니다"),
        ),
        "코치": (
            ("해봐요", "해봅시다"),
            ("챙겨봐요", "챙겨봅시다"),
            ("챙겨요", "챙겨봅시다"),
            ("보강해요", "보강해봅시다"),
            ("좋아요", "좋습니다"),
        ),
    }

    rewritten = text
    for source, target in replacements[persona]:
        rewritten = rewritten.replace(source, target)

    # 문맥상 필요한 최소한의 성격 차이는 본문 안에서 드러낸다. 안전/확인
    # 메시지에는 새로운 행동을 덧붙이지 않아 원문의 결정을 보존한다.
    if context == "general":
        lead_ins = {
            "악마": "핵심만 짚겠습니다. ",
            "천사": "부담 갖지 않아도 괜찮아요. ",
            "현실파이터": "지금 가능한 것부터 봅시다. ",
            "코치": "좋습니다, 방향을 잡아봅시다. ",
        }
        rewritten = lead_ins[persona] + rewritten
    elif context == "safety":
        lead_ins = {
            "악마": "지금은 무리하지 않는 게 우선입니다. ",
            "천사": "몸을 먼저 돌봐도 괜찮아요. ",
            "현실파이터": "지금은 회복을 우선순위로 둡시다. ",
            "코치": "좋은 훈련은 회복까지 포함합니다. ",
        }
        rewritten = lead_ins[persona] + rewritten
    elif context == "confirmation":
        lead_ins = {
            "악마": "정확히 확인하겠습니다. ",
            "천사": "편하게 하나만 더 알려주세요. ",
            "현실파이터": "판단에 필요한 것 하나만 확인합시다. ",
            "코치": "다음 안내를 위해 하나만 확인하겠습니다. ",
        }
        rewritten = lead_ins[persona] + rewritten
    elif context == "error":
        lead_ins = {
            "악마": "문제부터 바로잡겠습니다. ",
            "천사": "괜찮아요, 문제를 차근차근 확인해볼게요. ",
            "현실파이터": "원인부터 확인합시다. ",
            "코치": "잠시 점검하고 다시 이어가겠습니다. ",
        }
        rewritten = lead_ins[persona] + rewritten
    elif context == "status":
        lead_ins = {
            "악마": "확인했습니다. ",
            "천사": "좋아요, 차근차근 기록해둘게요. ",
            "현실파이터": "기록 기준을 잡았습니다. ",
            "코치": "좋습니다, 기록을 쌓아갑니다. ",
        }
        rewritten = lead_ins[persona] + rewritten
    elif context == "plan":
        lead_ins = {
            "악마": "계획은 단순하게 갑니다. ",
            "천사": "부담 없는 방향으로 맞춰볼게요. ",
            "현실파이터": "실행 가능한 기준으로 잡겠습니다. ",
            "코치": "좋습니다, 식사 계획을 잡아봅시다. ",
        }
        rewritten = lead_ins[persona] + rewritten

    return rewritten


def apply_persona(text: str, persona: str | None) -> str:
    if not text:
        return text

    # 이미 렌더링된 문장에 라벨과 꼬리말을 중첩하지 않는다.
    if text.startswith(_KNOWN_LABELS):
        return text

    normalized = normalize_persona(persona)
    label = _PERSONA_LABELS[normalized]
    context = _message_context(text)
    rendered = _rewrite_tone(text, normalized, context)

    # 끼니별 구조화 문장에는 라벨이 한 화면에서 반복되므로 본문만 반환한다.
    if context == "structured":
        return rendered
    # 페르소나 차이는 본문 안에서 만들고, 모든 상황에 범용 꼬리말을 강제로
    # 붙이지 않는다. 그래야 동일한 상투구 반복과 안전 문맥 충돌을 함께 피한다.
    return f"{label}: {rendered}"
