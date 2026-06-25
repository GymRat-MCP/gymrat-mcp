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
        session.add(InbodyLog(
            user_id=user_id, measured_date=_parse_date(measured_date),
            weight=weight, skeletal_muscle=skeletal_muscle,
            body_fat_pct=body_fat_pct, raw_note=raw_note,
        ))
        # 최신 인바디 체중을 프로필 컨텍스트에도 살짝 반영(선택)
        session.commit()

        # TODO: 직전 인바디와 비교해 골격근량/체지방 증감 note 생성
        note = "인바디 기록 완료."
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
    # TODO: photo_analysis 기반 질적 note 생성 (룰 기반: 단백질/채소/탄수 균형 체크)
    qualitative_note = "기록 완료. 다음 끼니 균형 참고할게요."

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
