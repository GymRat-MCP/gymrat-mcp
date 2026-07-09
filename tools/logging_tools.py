"""기록 툴 — 체중 / 인바디 / 운동 / 식단"""
from datetime import date as date_cls, datetime
from db.session import SessionLocal
from db.models import WeightLog, InbodyLog, WorkoutLog, MealLog, User, ExerciseSet
from tools.persona import (
    DEFAULT_PERSONA,
    apply_persona,
    get_persona,
    normalize_persona,
    persona_response_fields,
)
from tools.meal_intel import classify_meal_text, meal_feedback
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
    return meal_feedback(classify_meal_text(photo_analysis))


def _recent_meal_classifications(session, user_id: str, limit: int = 8) -> list[dict]:
    logs = (
        session.query(MealLog)
        .filter(MealLog.user_id == user_id)
        .order_by(MealLog.logged_at.desc(), MealLog.id.desc())
        .limit(limit)
        .all()
    )
    return [
        classify_meal_text(log.photo_analysis or "")
        for log in logs
    ]


def _meal_requires_confirmation(classification: dict) -> bool:
    return (
        classification.get("confidence") == "low"
        or classification.get("balance_flag") in {"unclear", "needs_more_info"}
    )


def _pending_meal_payload(
    user_id: str,
    meal_text: str,
    meal_time: str | None,
    classification: dict,
) -> dict:
    return {
        "user_id": user_id,
        "original_meal_text": meal_text,
        "meal_time": meal_time or classification.get("meal_time_detected"),
        "questions": classification.get("follow_up_questions", []),
        "confidence": classification.get("confidence"),
        "balance_flag": classification.get("balance_flag"),
        "classification": classification,
    }


def _save_meal_record(
    session,
    user_id: str,
    meal_text: str,
    meal_time: str | None,
    qualitative_note: str,
) -> None:
    session.add(MealLog(
        user_id=user_id, meal_time=meal_time,
        photo_analysis=meal_text, qualitative_note=qualitative_note,
    ))


def _meal_confirmation_note(classification: dict) -> str:
    question = (
        classification.get("follow_up_questions")
        or ["식단 구성을 조금만 더 알려주세요."]
    )[0]
    return f"이 식단은 아직 단정하기 어려워요. {question}"


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

        persona = normalize_persona(user.persona or DEFAULT_PERSONA)
        base_note = _inbody_note(previous, current)
        note = apply_persona(base_note, persona)
        session.commit()
        return {
            "saved": True,
            "profile_updated": True,
            "persona": persona,
            "note": note,
            "base_note": base_note,
            **persona_response_fields(
                persona, base_note, note, fallback_field="note"),
        }
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


def _workout_log_note(
    parsed: list[dict],
    needs: list[dict],
    auto_filled: list[str],
) -> str:
    valid_items = [item for item in (parsed or []) if item.get("exercise")]
    if not valid_items:
        return "운동 기록을 저장했어요. 다음 기록에는 운동명, 무게, 세트, 반복을 같이 알려주면 더 정확하게 볼게요."

    names = [item["exercise"] for item in valid_items[:3]]
    suffix = "" if len(valid_items) <= 3 else f" 외 {len(valid_items) - 3}개"
    if needs:
        return (
            f"{', '.join(names)}{suffix} 기록을 저장했어요. "
            "다만 빠진 무게·세트·반복이 있어 다음 처방 전에 한 번 더 확인하면 좋아요."
        )
    if auto_filled:
        return (
            f"{', '.join(names)}{suffix} 기록을 저장했어요. "
            "비어 있던 무게는 이전 기록을 참고해 채웠어요."
        )
    return f"{', '.join(names)}{suffix} 기록을 저장했어요. 다음 처방에 바로 반영할게요."


def _expand_to_sets(parsed: list[dict], user_id: str, log_date,
                    log_id: int | None) -> list[ExerciseSet]:
    """parsed 항목을 세트 단위 ExerciseSet 행으로 전개(P0 듀얼라이트).

    sets=N 이면 동일 무게/반복의 세트 N행(set_no 1..N)으로 편다(세트별 상세가
    아직 없으므로 근사). 종목명이 비면 건너뛰고, 맨몸은 weight=None 을 유지한다.
    """
    rows: list[ExerciseSet] = []
    for item in parsed or []:
        exercise = item.get("exercise")
        if not exercise:
            continue
        weight = item.get("weight")
        reps = item.get("reps")
        try:
            n_sets = int(item.get("sets"))
        except (TypeError, ValueError):
            n_sets = 1
        n_sets = max(1, n_sets)
        for set_no in range(1, n_sets + 1):
            rows.append(ExerciseSet(
                user_id=user_id, date=log_date, exercise=exercise,
                set_no=set_no, weight=weight, reps=reps, log_id=log_id,
            ))
    return rows


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

    persona = get_persona(user_id)
    session = SessionLocal()
    try:
        auto_filled = (_fill_from_history(session, user_id, parsed)
                       if confirm_with_history else [])
        # 자동 채움 후 남은 누락만 다시 계산 → 채워진 항목은 자연히 제외
        needs = needs_confirmation(parsed)
        log_date = _parse_date(date)
        log = WorkoutLog(
            user_id=user_id, date=log_date,
            raw_text=raw_text, parsed=parsed,
        )
        session.add(log)
        session.flush()   # log.id 확보 → 세트 역참조에 사용
        # 듀얼라이트(P0): parsed 를 세트 단위로 전개해 ExerciseSet 에도 기록
        for s in _expand_to_sets(parsed, user_id, log_date, log.id):
            session.add(s)
        session.commit()
        base_note = _workout_log_note(parsed, needs, auto_filled)
        note = apply_persona(base_note, persona)
        return {"parsed": parsed, "needs_confirmation": needs,
                "auto_filled": auto_filled, "saved": True,
                "persona": persona, "note": note, "base_note": base_note,
                **persona_response_fields(
                    persona, base_note, note, fallback_field="note")}
    except Exception as e:
        session.rollback()
        base_note = "운동 기록 저장에 실패했어요. 입력 내용을 한 번만 다시 확인해볼게요."
        note = apply_persona(base_note, persona)
        return {"parsed": parsed, "needs_confirmation": needs_confirmation(parsed),
                "auto_filled": [], "saved": False, "error": str(e),
                "persona": persona, "note": note, "base_note": base_note,
                **persona_response_fields(
                    persona, base_note, note, fallback_field="note")}
    finally:
        session.close()



def log_meal(user_id: str, photo_analysis: str,
            meal_time: str | None = None) -> dict:
    """식단 텍스트를 저장하고 질적 코멘트를 단다.

    photo_analysis는 기존 호환용 파라미터명이다. 사진 분석이 없는 호스트에서는
    사용자가 말한 식단 원문을 그대로 넘기면 된다.
    ⚠️ 가드레일: 정확 칼로리/그램 수치 ❌ → 질적 코칭만.
    """
    persona = get_persona(user_id)

    session = SessionLocal()
    try:
        recent_classifications = _recent_meal_classifications(session, user_id)
        classification = classify_meal_text(
            photo_analysis,
            meal_time=meal_time,
            recent_classifications=recent_classifications,
        )
        if _meal_requires_confirmation(classification):
            base_note = _meal_confirmation_note(classification)
            qualitative_note = apply_persona(base_note, persona)
            return {
                "saved": False,
                "pending_confirmation": True,
                "confirmation_required": True,
                "persona": persona,
                "meal_text": photo_analysis,
                **classification,
                "pending_meal_confirmation": _pending_meal_payload(
                    user_id, photo_analysis, meal_time, classification),
                "qualitative_note": qualitative_note,
                "base_qualitative_note": base_note,
                **persona_response_fields(
                    persona, base_note, qualitative_note,
                    fallback_field="qualitative_note"),
            }

        base_note = meal_feedback(classification)
        qualitative_note = apply_persona(base_note, persona)
        _save_meal_record(
            session, user_id, photo_analysis,
            meal_time or classification.get("meal_time_detected"),
            qualitative_note,
        )
        session.commit()
        return {
            "saved": True,
            "pending_confirmation": False,
            "confirmation_required": False,
            "persona": persona,
            "meal_text": photo_analysis,
            **classification,
            "qualitative_note": qualitative_note,
            "base_qualitative_note": base_note,
            **persona_response_fields(
                persona, base_note, qualitative_note,
                fallback_field="qualitative_note"),
        }
    except Exception as e:
        session.rollback()
        return {"saved": False, "error": str(e)}
    finally:
        session.close()


def confirm_meal_details(
    user_id: str,
    original_meal_text: str,
    clarification_text: str,
    meal_time: str | None = None,
) -> dict:
    """보충 답변을 받아 2-step 식단 기록을 최종 저장한다."""
    persona = get_persona(user_id)
    combined_meal_text = (
        f"{original_meal_text}. 보충: {clarification_text}"
        if clarification_text else original_meal_text
    )

    session = SessionLocal()
    try:
        recent_classifications = _recent_meal_classifications(session, user_id)
        classification = classify_meal_text(
            combined_meal_text,
            meal_time=meal_time,
            recent_classifications=recent_classifications,
        )
        if _meal_requires_confirmation(classification):
            base_note = _meal_confirmation_note(classification)
            qualitative_note = apply_persona(base_note, persona)
            return {
                "saved": False,
                "pending_confirmation": True,
                "confirmation_required": True,
                "confirmed": False,
                "persona": persona,
                "meal_text": combined_meal_text,
                "original_meal_text": original_meal_text,
                "clarification_text": clarification_text,
                **classification,
                "pending_meal_confirmation": _pending_meal_payload(
                    user_id, original_meal_text, meal_time, classification),
                "qualitative_note": qualitative_note,
                "base_qualitative_note": base_note,
                **persona_response_fields(
                    persona, base_note, qualitative_note,
                    fallback_field="qualitative_note"),
            }

        base_note = meal_feedback(classification)
        qualitative_note = apply_persona(base_note, persona)
        _save_meal_record(
            session, user_id, combined_meal_text,
            meal_time or classification.get("meal_time_detected"),
            qualitative_note,
        )
        session.commit()
        return {
            "saved": True,
            "pending_confirmation": False,
            "confirmation_required": False,
            "confirmed": True,
            "persona": persona,
            "meal_text": combined_meal_text,
            "original_meal_text": original_meal_text,
            "clarification_text": clarification_text,
            **classification,
            "qualitative_note": qualitative_note,
            "base_qualitative_note": base_note,
            **persona_response_fields(
                persona, base_note, qualitative_note,
                fallback_field="qualitative_note"),
        }
    except Exception as e:
        session.rollback()
        return {"saved": False, "confirmed": False, "error": str(e)}
    finally:
        session.close()
