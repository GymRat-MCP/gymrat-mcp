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
    parse_workout, normalize_exercise, needs_confirmation, parse_relative_date,
)
from tools.analysis import _detect_prs, pr_headline


def _today():
    return datetime.now().date()


def _parse_date(s: str | None):
    """날짜 문자열을 date로. YYYY-MM-DD 우선, 아니면 상대표현("어제", "3주 전"),
    그래도 못 읽으면 오늘로 폴백(P4)."""
    if not s:
        return _today()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return parse_relative_date(s) or _today()


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


def _meal_quality_note(meal_text: str) -> str:
    return meal_feedback(classify_meal_text(meal_text))


def _recent_meal_classifications(session, user_id: str, limit: int = 8) -> list[dict]:
    logs = (
        session.query(MealLog)
        .filter(MealLog.user_id == user_id)
        .order_by(MealLog.logged_at.desc(), MealLog.id.desc())
        .limit(limit)
        .all()
    )
    return [
        classify_meal_text(log.meal_text or "")
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
        meal_text=meal_text, qualitative_note=qualitative_note,
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
    persona = get_persona(user_id)
    session = SessionLocal()
    try:
        session.add(WeightLog(
            user_id=user_id, date=_parse_date(date),
            weight=weight, body_fat=body_fat,
        ))
        session.commit()
        body_fat_text = (
            f", 체지방률 {body_fat:.1f}%" if body_fat is not None else ""
        )
        base_note = (
            f"체중 {weight:.1f}kg{body_fat_text} 기록을 저장했어요. "
            "다음 추세 분석에 반영할게요."
        )
        note = apply_persona(base_note, persona)
        return {
            "saved": True,
            "weight": weight,
            "body_fat": body_fat,
            "persona": persona,
            "note": note,
            "base_note": base_note,
            **persona_response_fields(
                persona, base_note, note, fallback_field="note"),
        }
    except Exception as e:
        session.rollback()
        base_note = "체중 기록 저장에 실패했어요. 입력 내용을 한 번만 다시 확인해볼게요."
        note = apply_persona(base_note, persona)
        return {
            "saved": False,
            "error": str(e),
            "persona": persona,
            "note": note,
            "base_note": base_note,
            **persona_response_fields(
                persona, base_note, note, fallback_field="note"),
        }
    finally:
        session.close()


def log_inbody(user_id: str, weight: float | None = None,
               skeletal_muscle: float | None = None,
               body_fat_pct: float | None = None,
               measured_date: str | None = None,
               raw_note: str | None = None) -> dict:
    """사용자가 텍스트로 알려준 인바디 측정 수치를 저장하고 프로필에 반영한다.

    체중·골격근량·체지방률 등 사용자가 직접 불러준 정확 수치를 받는다.
    추정이 아니라 실측값이므로 저장해도 안전.
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
    prs: list[dict] | None = None,
) -> str:
    valid_items = [item for item in (parsed or []) if item.get("exercise")]
    if not valid_items:
        return "운동 기록을 저장했어요. 다음 기록에는 운동명, 무게, 세트, 반복을 같이 알려주면 더 정확하게 볼게요."

    names = [item["exercise"] for item in valid_items[:3]]
    suffix = "" if len(valid_items) <= 3 else f" 외 {len(valid_items) - 3}개"
    if needs:
        body = (
            f"{', '.join(names)}{suffix} 기록을 저장했어요. "
            "다만 빠진 무게·세트·반복이 있어 다음 처방 전에 한 번 더 확인하면 좋아요."
        )
    elif auto_filled:
        body = (
            f"{', '.join(names)}{suffix} 기록을 저장했어요. "
            "비어 있던 무게는 이전 기록을 참고해 채웠어요."
        )
    else:
        body = f"{', '.join(names)}{suffix} 기록을 저장했어요. 다음 처방에 바로 반영할게요."

    # PR 축하 문구를 앞에 붙여 도파민 먼저(있을 때만).
    head = pr_headline(prs or [])
    return f"{head} {body}" if head else body


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
        # 항목별 date 오버라이드 허용(P4): 온보딩 시 종목마다 다른 과거 날짜.
        item_date = _parse_date(item["date"]) if item.get("date") else log_date
        try:
            n_sets = int(item.get("sets"))
        except (TypeError, ValueError):
            n_sets = 1
        n_sets = max(1, n_sets)
        for set_no in range(1, n_sets + 1):
            rows.append(ExerciseSet(
                user_id=user_id, date=item_date, exercise=exercise,
                set_no=set_no, weight=weight, reps=reps, log_id=log_id,
            ))
    return rows


def _resolve_session_date(parsed: list[dict], top_level_date: str | None):
    """항목별 상대날짜를 실제 날짜(ISO)로 정규화하고 세션 대표 날짜를 정한다.

    - 각 항목의 date("4주 전" 등)를 계산된 날짜로 바꿔 parsed에 되박는다(JSON 정리).
    - WorkoutLog.date(세션 대표): top-level date 우선, 없으면 항목 날짜 중 가장 이른 날,
      항목 날짜도 없으면 오늘.
    ⚠️ 예전엔 항목 date를 무시하고 WorkoutLog.date를 항상 오늘로 저장했다. 그러면
      백필 세션이 전부 같은 날짜로 뭉쳐 date 정렬이 동점→불특정이 되고(특히 Postgres),
      루틴의 직전무게·볼륨추세가 꼬였다. 계산 로직(parse_relative_date)은 이미 있었고
      ExerciseSet엔 반영됐는데 WorkoutLog에만 연결이 빠져 있던 것을 메운다.
    """
    item_dates = []
    for item in parsed:
        if item.get("date"):
            d = _parse_date(item["date"])
            item["date"] = d.isoformat()
            item_dates.append(d)
    if top_level_date:
        return _parse_date(top_level_date)
    if item_dates:
        return min(item_dates)
    return _today()


def _injury_caution(user_id: str, parsed: list[dict]) -> str | None:
    """저장하는 종목이 사용자의 부상 금기 동작이면 부드러운 경고 문구를 만든다(안전).

    routine의 부상 규칙(영문 패턴)을 재사용하고, 로그의 한글 정규명을 라이브러리
    영문 대표명으로 브리지해 대조한다. 매칭이 없으면 None(경고 없음).
    부상은 지금까지 루틴 처방에서만 쓰였는데, 정작 사용자가 금기 동작을 직접
    기록할 때 침묵하던 갭을 메운다.
    """
    from tools.routine import _injury_filters
    from tools.exercise_map import KO_CANON_TO_LIB

    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        injuries = getattr(user, "injuries", None) if user else None
    finally:
        session.close()
    if not injuries:
        return None
    _, blocked = _injury_filters(injuries)
    if not blocked:
        return None

    flagged: list[str] = []
    for item in parsed:
        ex = item.get("exercise")
        if not ex:
            continue
        en = KO_CANON_TO_LIB.get(ex, "")
        haystack = f"{ex} {en}".lower()
        if ex not in flagged and any(p in haystack for p in blocked):
            flagged.append(ex)
    if not flagged:
        return None
    return (f"⚠️ {', '.join(flagged)}는 부상 부위에 무리가 갈 수 있는 동작이에요. "
            "통증이 있으면 무게를 낮추거나 대체 동작을 추천해줄게요.")


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
        log_date = _resolve_session_date(parsed, date)
        log = WorkoutLog(
            user_id=user_id, date=log_date,
            raw_text=raw_text, parsed=parsed,
        )
        session.add(log)
        session.flush()   # log.id 확보 → 세트 역참조에 사용
        # PR 판정(P2): 이번 세트를 add 하기 전에 과거 기록과 비교해야 자기
        # 자신과 비교하지 않는다.
        prs = _detect_prs(session, user_id, parsed)
        # 듀얼라이트(P0): parsed 를 세트 단위로 전개해 ExerciseSet 에도 기록
        for s in _expand_to_sets(parsed, user_id, log_date, log.id):
            session.add(s)
        session.commit()
        base_note = _workout_log_note(parsed, needs, auto_filled, prs)
        caution = _injury_caution(user_id, parsed)
        if caution:
            base_note = f"{base_note} {caution}"
        note = apply_persona(base_note, persona)
        return {"parsed": parsed, "needs_confirmation": needs,
                "auto_filled": auto_filled, "prs": prs, "saved": True,
                "persona": persona, "note": note, "base_note": base_note,
                **persona_response_fields(
                    persona, base_note, note, fallback_field="note")}
    except Exception as e:
        session.rollback()
        base_note = "운동 기록 저장에 실패했어요. 입력 내용을 한 번만 다시 확인해볼게요."
        note = apply_persona(base_note, persona)
        return {"parsed": parsed, "needs_confirmation": needs_confirmation(parsed),
                "auto_filled": [], "prs": [], "saved": False, "error": str(e),
                "persona": persona, "note": note, "base_note": base_note,
                **persona_response_fields(
                    persona, base_note, note, fallback_field="note")}
    finally:
        session.close()



def _delete_sets_for_log(session, log_id: int) -> int:
    """해당 WorkoutLog의 ExerciseSet 행을 모두 삭제하고 삭제 수를 반환한다."""
    return (session.query(ExerciseSet)
            .filter(ExerciseSet.log_id == log_id)
            .delete(synchronize_session=False))


def edit_workout(user_id: str, log_id: int,
                 exercises: list[dict] | None = None,
                 raw_text: str | None = None,
                 date: str | None = None) -> dict:
    """기존 운동 기록을 수정한다(P4). 무게·반복 오타 교정, 날짜 정정 등.

    - exercises: 주면 parsed를 통째로 교체하고 ExerciseSet도 다시 전개한다.
      (부분 수정도 호스트가 전체 배열을 다시 채워 넘기는 방식으로 처리)
    - date: 주면 로그와 그 세트들의 날짜를 함께 옮긴다(상대표현도 인식).
    - 본인(user_id) 소유 로그만 수정 — 남의 기록은 건드리지 않는다.
    듀얼라이트(WorkoutLog·ExerciseSet) 정합성을 함께 갱신한다.
    """
    session = SessionLocal()
    try:
        log = session.get(WorkoutLog, log_id)
        if log is None or log.user_id != user_id:
            return {"updated": False, "error": "해당 기록을 찾을 수 없어요."}

        new_date = _parse_date(date) if date else log.date
        if exercises is not None:
            parsed = [dict(item) for item in exercises]
            for item in parsed:
                item["exercise"] = normalize_exercise(item.get("exercise", ""))
            log.parsed = parsed
            if raw_text is not None:
                log.raw_text = raw_text
            log.date = new_date
            # 세트 재전개: 기존 세트 제거 후 새 parsed로 다시 생성.
            _delete_sets_for_log(session, log.id)
            for s in _expand_to_sets(parsed, user_id, new_date, log.id):
                session.add(s)
        else:
            # parsed 변경 없이 날짜/원문만 정정.
            if raw_text is not None:
                log.raw_text = raw_text
            if date:
                log.date = new_date
                (session.query(ExerciseSet)
                 .filter(ExerciseSet.log_id == log.id)
                 .update({ExerciseSet.date: new_date},
                         synchronize_session=False))

        session.commit()
        return {"updated": True, "log_id": log.id,
                "date": log.date.isoformat(), "parsed": log.parsed,
                "note": "기록을 수정했어요. 통계에도 바로 반영돼요."}
    except Exception as e:
        session.rollback()
        return {"updated": False, "error": str(e)}
    finally:
        session.close()


def delete_workout(user_id: str, log_id: int) -> dict:
    """운동 기록을 삭제한다(P4). WorkoutLog와 연결된 ExerciseSet를 함께 지운다.

    본인(user_id) 소유 로그만 삭제. 잘못 남긴 기록 제거 후 통계에서도 빠진다.
    """
    session = SessionLocal()
    try:
        log = session.get(WorkoutLog, log_id)
        if log is None or log.user_id != user_id:
            return {"deleted": False, "error": "해당 기록을 찾을 수 없어요."}
        n_sets = _delete_sets_for_log(session, log.id)
        session.delete(log)
        session.commit()
        return {"deleted": True, "log_id": log_id, "removed_sets": n_sets,
                "note": "기록을 삭제했어요. 통계에서도 제외돼요."}
    except Exception as e:
        session.rollback()
        return {"deleted": False, "error": str(e)}
    finally:
        session.close()


def get_recent_workouts(user_id: str, limit: int = 10) -> dict:
    """최근 운동 기록을 log_id와 함께 반환한다(수정·삭제 대상 식별용).

    edit_workout/delete_workout는 log_id가 필요한데 사용자는 id를 모른다.
    "아까 그거 지워줘/고쳐줘" 같은 요청 전에 이 툴로 최근 기록과 id를 확인한다.
    반환: {workouts: [{log_id, date, exercises[], summary}], count}
    """
    session = SessionLocal()
    try:
        logs = (session.query(WorkoutLog)
                .filter(WorkoutLog.user_id == user_id)
                .order_by(WorkoutLog.date.desc(), WorkoutLog.id.desc())
                .limit(max(1, min(50, limit)))
                .all())
        items = []
        for lg in logs:
            names = [e.get("exercise") for e in (lg.parsed or [])
                     if e.get("exercise")]
            items.append({
                "log_id": lg.id,
                "date": lg.date.isoformat(),
                "exercises": names,
                "summary": lg.raw_text or ", ".join(names) or "운동 기록",
            })
        return {"workouts": items, "count": len(items)}
    finally:
        session.close()


def log_meal(user_id: str, meal_text: str,
            meal_time: str | None = None) -> dict:
    """식단 텍스트를 저장하고 질적 코멘트를 단다.

    meal_text에는 사용자가 말한 식단 원문을 그대로 넘긴다.
    ⚠️ 가드레일: 정확 칼로리/그램 수치 ❌ → 질적 코칭만.
    """
    persona = get_persona(user_id)

    session = SessionLocal()
    try:
        recent_classifications = _recent_meal_classifications(session, user_id)
        classification = classify_meal_text(
            meal_text,
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
                "meal_text": meal_text,
                **classification,
                "pending_meal_confirmation": _pending_meal_payload(
                    user_id, meal_text, meal_time, classification),
                "qualitative_note": qualitative_note,
                "base_qualitative_note": base_note,
                **persona_response_fields(
                    persona, base_note, qualitative_note,
                    fallback_field="qualitative_note"),
            }

        base_note = meal_feedback(classification)
        qualitative_note = apply_persona(base_note, persona)
        _save_meal_record(
            session, user_id, meal_text,
            meal_time or classification.get("meal_time_detected"),
            qualitative_note,
        )
        session.commit()
        return {
            "saved": True,
            "pending_confirmation": False,
            "confirmation_required": False,
            "persona": persona,
            "meal_text": meal_text,
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
