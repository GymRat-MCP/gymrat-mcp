"""운동 루틴 처방 — 목표/이력 기반, 점진적 과부하 자동 반영

결정론적 룰 기반(LLM 호출 X)이라 안정성 점수에 유리.
form_cues는 exercise_library에서 가져옴 → 텍스트 자세 큐.
"""
from db.session import SessionLocal
from db.models import ExerciseLibrary, WorkoutLog, User


def generate_routine(user_id: str, focus: str | None = None,
                     available_days: int = 3,
                     session_minutes: int | None = None) -> dict:
    """오늘/이번 주 루틴을 처방한다.

    focus: "가슴"|"하체"|... (None이면 분할 자동 선택)
    반환: {split, exercises[], rationale}
    """
    profile = _load_profile(user_id)
    history = _recent_workouts(user_id)

    # TODO: available_days → 분할 결정 (예: 3일=상하체/PPL)
    split = _decide_split(available_days, focus)

    # TODO: split별 종목 선택 + 직전 기록 기반 target_load(점진적 과부하)
    exercises = _build_exercises(split, focus, history)

    # TODO: 정체/성장 판단해 rationale 문장 생성
    rationale = "TODO: 이력 기반 처방 근거"

    return {"split": split, "exercises": exercises, "rationale": rationale}


def _load_profile(user_id: str):
    session = SessionLocal()
    try:
        return session.get(User, user_id)
    finally:
        session.close()


def _recent_workouts(user_id: str, limit: int = 20):
    session = SessionLocal()
    try:
        return (session.query(WorkoutLog)
                .filter(WorkoutLog.user_id == user_id)
                .order_by(WorkoutLog.date.desc())
                .limit(limit).all())
    finally:
        session.close()


def _decide_split(available_days: int, focus: str | None) -> str:
    # TODO: 일수 기반 분할 매핑
    return "TODO 분할"


def _build_exercises(split: str, focus: str | None, history) -> list[dict]:
    # TODO: exercise_library 조회 → 종목별 sets/reps/target_load/form_cues
    return []


def _form_cues(exercise_name: str) -> list[str]:
    session = SessionLocal()
    try:
        ex = (session.query(ExerciseLibrary)
              .filter(ExerciseLibrary.name == exercise_name).first())
        return ex.form_cues if ex and ex.form_cues else []
    finally:
        session.close()
