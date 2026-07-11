"""관리/테스트 툴 — 유저 데이터 초기화 등.

PlayMCP 콘솔에서 반복 테스트할 때 서버 SSH 없이 대화로 초기화하기 위한 툴.
⚠️ 파괴적: 해당 user_id의 모든 기록·프로필을 지운다(운동 라이브러리는 유지).
스코프는 항상 단일 user_id 로 한정 — 다른 사용자 데이터는 건드리지 않는다.
"""
from db.session import SessionLocal
from db.models import (
    User, WeightLog, InbodyLog, WorkoutLog, ExerciseSet, MealLog, Program,
)

# 초기화 대상: (라벨, 모델, user 식별 컬럼). exercise_library(정적 시드)는 제외.
_USER_TABLES = [
    ("exercise_sets", ExerciseSet, ExerciseSet.user_id),
    ("workout_logs", WorkoutLog, WorkoutLog.user_id),
    ("weight_logs", WeightLog, WeightLog.user_id),
    ("inbody_logs", InbodyLog, InbodyLog.user_id),
    ("meal_logs", MealLog, MealLog.user_id),
    ("programs", Program, Program.user_id),
    ("users", User, User.id),   # 프로필은 마지막에(자식 기록부터 지운 뒤)
]


def reset_user_data(user_id: str) -> dict:
    """해당 사용자의 모든 기록과 프로필을 삭제해 완전 초기 상태로 되돌린다.

    운동 로그·세트·체중·인바디·식단·프로그램·프로필을 전부 지운다.
    운동 라이브러리(정적 시드)는 유지하므로 재시드가 필요 없다.
    ⚠️ 되돌릴 수 없다. 반드시 요청한 본인(user_id) 데이터만 지운다.
    """
    if not user_id:
        return {"reset": False, "error": "user_id가 필요해요."}

    session = SessionLocal()
    try:
        deleted: dict[str, int] = {}
        for label, model, col in _USER_TABLES:
            n = (session.query(model)
                 .filter(col == user_id)
                 .delete(synchronize_session=False))
            deleted[label] = int(n or 0)
        session.commit()
        total = sum(deleted.values())
        return {
            "reset": True,
            "user_id": user_id,
            "deleted": deleted,
            "total_deleted": total,
            "assistant_message": (
                "데이터를 완전히 초기화했어요. 이제 처음부터 시작할 수 있어요! "
                "먼저 목표·경험·장비 같은 프로필부터 알려주세요."
            ),
        }
    except Exception as e:
        session.rollback()
        return {"reset": False, "error": str(e)}
    finally:
        session.close()
