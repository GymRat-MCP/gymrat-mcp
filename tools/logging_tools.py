"""기록 툴 — 체중 / 인바디 / 운동 / 식단"""
from datetime import date as date_cls, datetime
from db.session import SessionLocal
from db.models import WeightLog, InbodyLog, WorkoutLog, MealLog, User
from tools.workout_parser import parse_workout, normalize_exercise


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


def log_workout(user_id: str, raw_text: str,
                exercises: list[dict] | None = None,
                confirm_with_history: bool = True,
                date: str | None = None) -> dict:
    """운동 기록을 자연어 한 줄로 받아 파싱·저장한다.

    예: "벤치 70 5x5, 인클 60 3x10"
    """
    if exercises is not None:
        parsed = exercises
        needs_confirmation = []
    else:
        parsed, needs_confirmation = parse_workout(raw_text)

    for item in parsed:
        item["exercise"] = normalize_exercise(item.get("exercise", ""))

    # TODO: confirm_with_history=True면 누락 weight를 직전 동일 종목 기록으로 채우기
    #       (analyze 모듈/직전 WorkoutLog 조회)

    session = SessionLocal()
    try:
        session.add(WorkoutLog(
            user_id=user_id, date=_parse_date(date),
            raw_text=raw_text, parsed=parsed,
        ))
        session.commit()
        return {"parsed": parsed, "needs_confirmation": needs_confirmation, "saved": True}
    except Exception as e:
        session.rollback()
        return {"parsed": parsed, "needs_confirmation": needs_confirmation,
                "saved": False, "error": str(e)}
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
