"""기록 툴 — 체중 / 인바디 / 운동 / 식단"""
from datetime import date as date_cls, datetime
from db.session import SessionLocal
from db.models import WeightLog, InbodyLog, WorkoutLog, MealLog, User
from tools.workout_parser import (
    parse_workout, normalize_exercise, needs_confirmation,
)


def _today():
    return datetime.now().date()


def _parse_date(s: str | None):
    if not s:
        return _today()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return _today()


def _fmt_delta(value: float | None, unit: str) -> str | None:
    if value is None:
        return None
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}{unit}"


def _inbody_note(previous: InbodyLog | None, current: InbodyLog) -> str:
    if previous is None:
        return "첫 인바디 기록이에요. 앞으로 변화 추적의 기준점으로 삼을게요."

    parts = []
    if current.weight is not None and previous.weight is not None:
        parts.append(f"체중 {_fmt_delta(current.weight - previous.weight, 'kg')}")
    if current.skeletal_muscle is not None and previous.skeletal_muscle is not None:
        parts.append(f"골격근량 {_fmt_delta(current.skeletal_muscle - previous.skeletal_muscle, 'kg')}")
    if current.body_fat_pct is not None and previous.body_fat_pct is not None:
        parts.append(f"체지방률 {_fmt_delta(current.body_fat_pct - previous.body_fat_pct, '%p')}")

    if not parts:
        return "인바디 기록 완료. 비교 가능한 이전 수치가 더 쌓이면 변화도 같이 볼게요."

    return "직전 인바디 대비 " + ", ".join(parts) + " 변화가 있어요."


def _meal_quality_note(photo_analysis: str) -> str:
    text = (photo_analysis or "").lower()
    protein_words = ["단백질", "닭", "계란", "달걀", "고기", "소고기", "돼지", "생선",
                     "연어", "참치", "두부", "콩", "그릭요거트", "요거트", "쉐이크"]
    veggie_words = ["채소", "야채", "샐러드", "나물", "브로콜리", "양배추", "상추",
                    "오이", "토마토", "김치", "버섯"]
    carb_words = ["밥", "현미", "쌀", "고구마", "감자", "빵", "면", "파스타",
                  "오트", "시리얼", "떡"]

    has_protein = any(word in text for word in protein_words)
    has_veggie = any(word in text for word in veggie_words)
    has_carb = any(word in text for word in carb_words)

    missing = []
    if not has_protein:
        missing.append("단백질")
    if not has_veggie:
        missing.append("채소")
    if not has_carb:
        missing.append("탄수화물")

    if not missing:
        return "단백질, 채소, 탄수화물 구성이 꽤 균형 있어 보여요. 이 흐름 유지해봐요."
    if len(missing) == 3:
        return "사진 설명만으로는 구성이 선명하지 않아요. 다음 기록엔 주된 단백질, 채소, 탄수화물을 같이 알려주세요."
    if missing == ["탄수화물"]:
        return "단백질과 채소는 괜찮아 보여요. 운동 전후라면 탄수화물도 적당히 챙기면 좋아요."
    if missing == ["채소"]:
        return "주요 에너지원은 있어 보여요. 다음 끼니엔 채소를 더해 포만감과 균형을 챙겨봐요."
    if missing == ["단백질"]:
        return "탄수화물과 곁들임은 보여요. 근육 회복을 위해 다음 끼니엔 단백질을 보강해봐요."
    return f"{'·'.join(missing)} 쪽이 조금 비어 보여요. 다음 끼니에서 부족한 축만 보완하면 됩니다."


def log_weight(user_id: str, weight: float, body_fat: float | None = None,
               date: str | None = None) -> dict:
    """체중(kg)과 선택적 체지방률(%)을 기록한다."""
    session = SessionLocal()
    try:
        session.add(WeightLog(
            user_id=user_id, date=_parse_date(date),
            weight=weight, body_fat=body_fat,
        ))
        session.commit()
        return {"saved": True, "weight": weight}
    except Exception as e:
        session.rollback()
        return {"saved": False, "error": str(e)}
    finally:
        session.close()


def log_inbody(user_id: str, weight: float | None = None,
               skeletal_muscle: float | None = None,
               body_fat_pct: float | None = None,
               measured_date: str | None = None,
               raw_note: str | None = None) -> dict:
    """인바디 사진에서 추출한 값을 저장하고 프로필에 반영한다.

    비전 추출(호스트 LLM)이 끝난 수치를 받는다. 정확 수치는 화면에
    박혀 있어 OCR 신뢰도가 높음 — 추정이 아니므로 저장해도 안전.
    """
    session = SessionLocal()
    try:
        parsed_date = _parse_date(measured_date)
        previous = (
            session.query(InbodyLog)
            .filter(InbodyLog.user_id == user_id)
            .order_by(InbodyLog.measured_date.desc(), InbodyLog.id.desc())
            .first()
        )
        current = InbodyLog(
            user_id=user_id, measured_date=parsed_date,
            weight=weight, skeletal_muscle=skeletal_muscle,
            body_fat_pct=body_fat_pct, raw_note=raw_note,
        )
        session.add(current)

        user = session.get(User, user_id)
        if not user:
            user = User(id=user_id)
            session.add(user)

        summary_parts = [f"최근 인바디 {parsed_date.isoformat()}"]
        if weight is not None:
            summary_parts.append(f"체중 {weight:.1f}kg")
        if skeletal_muscle is not None:
            summary_parts.append(f"골격근량 {skeletal_muscle:.1f}kg")
        if body_fat_pct is not None:
            summary_parts.append(f"체지방률 {body_fat_pct:.1f}%")
        user.summary_context = " / ".join(summary_parts)

        note = _inbody_note(previous, current)
        session.commit()
        return {"saved": True, "profile_updated": True, "note": note}
    except Exception as e:
        session.rollback()
        return {"saved": False, "error": str(e)}
    finally:
        session.close()


def _fill_from_history(session, user_id: str, parsed: list[dict]) -> list[str]:
    """weight=None인 항목을 직전 동일 종목 기록으로 채운다. in-place."""
    if not any(item.get("weight") is None for item in parsed):
        return []

    recent_logs = (
        session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user_id)
        .order_by(WorkoutLog.date.desc(), WorkoutLog.logged_at.desc())
        .limit(30)
        .all()
    )

    last_weight: dict[str, float] = {}
    for log in recent_logs:
        for entry in (log.parsed or []):
            ex, w = entry.get("exercise"), entry.get("weight")
            if ex and w is not None and ex not in last_weight:
                last_weight[ex] = w

    auto_filled = []
    for item in parsed:
        if item.get("weight") is None:
            ex = item.get("exercise", "")
            if ex in last_weight:
                item["weight"] = last_weight[ex]
                auto_filled.append(f"{ex}: 이전 기록 {last_weight[ex]}kg 자동 적용")

    return auto_filled


def log_workout(user_id: str, raw_text: str,
                exercises: list[dict] | None = None,
                date: str | None = None,
                confirm_with_history: bool = True) -> dict:
    """운동 기록을 자연어 한 줄로 받아 파싱·저장한다.

    예: "벤치 70 5x5, 인클 60 3x10"

    confirm_with_history=True면 무게가 비었을 때 직전 동일 종목 기록으로
    자동으로 채운다(채운 항목은 needs_confirmation에서 빠진다).
    """
    if exercises is not None:
        parsed = exercises
    else:
        parsed, _ = parse_workout(raw_text)

    for item in parsed:
        item["exercise"] = normalize_exercise(item.get("exercise", ""))

    session = SessionLocal()
    try:
        auto_filled = (_fill_from_history(session, user_id, parsed)
                       if confirm_with_history else [])
        # 자동 채움 후 남은 누락만 다시 계산 → 채워진 항목은 자연히 제외
        needs = needs_confirmation(parsed)
        session.add(WorkoutLog(
            user_id=user_id, date=_parse_date(date),
            raw_text=raw_text, parsed=parsed,
        ))
        session.commit()
        return {"parsed": parsed, "needs_confirmation": needs,
                "auto_filled": auto_filled, "saved": True}
    except Exception as e:
        session.rollback()
        return {"parsed": parsed, "needs_confirmation": needs_confirmation(parsed),
                "auto_filled": [], "saved": False, "error": str(e)}
    finally:
        session.close()



def log_meal(user_id: str, photo_analysis: str,
            meal_time: str | None = None) -> dict:
    """식단 사진 분석 결과(호스트 LLM 텍스트)를 저장하고 질적 코멘트를 단다.

    ⚠️ 가드레일: 정확 칼로리/그램 수치 ❌ → 질적 코칭만.
    """
    qualitative_note = _meal_quality_note(photo_analysis)

    session = SessionLocal()
    try:
        session.add(MealLog(
            user_id=user_id, meal_time=meal_time,
            photo_analysis=photo_analysis, qualitative_note=qualitative_note,
        ))
        session.commit()
        return {"saved": True, "qualitative_note": qualitative_note}
    except Exception as e:
        session.rollback()
        return {"saved": False, "error": str(e)}
    finally:
        session.close()
