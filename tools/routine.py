"""운동 루틴 처방 — 목표/이력 기반, 점진적 과부하 자동 반영

결정론적 룰 기반(LLM 호출 X)이라 안정성 점수에 유리.
form_cues는 exercise_library에서 가져옴(영문 단계) → 출력 시 호스트 LLM이 한글화.
"""
from datetime import datetime, timedelta
from db.session import SessionLocal
from db.models import ExerciseLibrary, WorkoutLog, User
from tools.analysis import _trend_volume
from tools.profile import normalize_goal, normalize_experience
from tools.workout_parser import normalize_exercise
from tools.exercise_map import lib_to_ko_canon


# ── 분할(split) 정의 ───────────────────────────────────────
# 부위 그룹 (ExerciseLibrary.target 한글 부위명 기준)
_PUSH = ["가슴", "어깨", "삼두"]
_PULL = ["등", "이두", "전완"]
_LEGS = ["하체", "종아리"]
_UPPER = ["가슴", "등", "어깨", "삼두", "이두"]
_LOWER = ["하체", "종아리", "코어"]
_FULL = ["가슴", "등", "하체", "어깨"]

# 일수 → 하루씩의 (라벨, 타깃부위들) 순환 계획
_SPLIT_PLANS = {
    1: [("전신", _FULL)],
    2: [("전신 A", _FULL), ("전신 B", ["등", "하체", "어깨", "코어"])],
    3: [("Push(가슴·어깨·삼두)", _PUSH),
        ("Pull(등·이두)", _PULL),
        ("Legs(하체)", _LEGS + ["코어"])],
    4: [("상체 A", _UPPER), ("하체 A", _LOWER),
        ("상체 B", _UPPER), ("하체 B", _LOWER)],
    5: [("Push", _PUSH), ("Pull", _PULL), ("Legs", _LEGS + ["코어"]),
        ("상체", _UPPER), ("하체", _LOWER)],
    6: [("Push A", _PUSH), ("Pull A", _PULL), ("Legs A", _LEGS + ["코어"]),
        ("Push B", _PUSH), ("Pull B", _PULL), ("Legs B", _LEGS + ["코어"])],
}

# focus(집중 부위) → 우선순위 타깃들(focus 먼저 + 시너지 근육)
_FOCUS_TARGETS = {
    "가슴": ["가슴", "삼두", "어깨"],
    "등": ["등", "이두", "전완"],
    "어깨": ["어깨", "삼두"],
    "하체": ["하체", "종아리"],
    "이두": ["이두", "전완"],
    "삼두": ["삼두", "가슴"],
    "팔": ["이두", "삼두", "전완"],
    "코어": ["코어"],
    "종아리": ["종아리"],
}

# 호스트 LLM이 focus를 영문·변형으로 보낼 때 한글 정규 부위로 매핑.
# (DB target과 _FOCUS_TARGETS 키가 전부 한글이라 매핑 없으면 0건 → 빈 루틴)
_FOCUS_ALIASES = {
    # 영문
    "chest": "가슴", "pec": "가슴", "pecs": "가슴",
    "back": "등", "lat": "등", "lats": "등",
    "shoulder": "어깨", "shoulders": "어깨", "delt": "어깨",
    "delts": "어깨", "deltoid": "어깨", "deltoids": "어깨",
    "leg": "하체", "legs": "하체", "lower body": "하체",
    "lower-body": "하체", "lowerbody": "하체", "lower": "하체",
    "quad": "하체", "quads": "하체", "glute": "하체", "glutes": "하체",
    "hamstring": "하체", "hamstrings": "하체",
    "bicep": "이두", "biceps": "이두",
    "tricep": "삼두", "triceps": "삼두",
    "arm": "팔", "arms": "팔",
    "core": "코어", "ab": "코어", "abs": "코어", "abdominals": "코어",
    "calf": "종아리", "calves": "종아리",
    # 한글 변형
    "다리": "하체", "허벅지": "하체", "둔근": "하체", "엉덩이": "하체", "둔근/하체": "하체",
    "복근": "코어", "복부": "코어", "배": "코어",
    "흉근": "가슴", "광배": "등", "삼각근": "어깨",
}

# 부상 키워드 → (후순위로 미룰 target 부위, 제외할 영문 종목명 패턴).
# 다친 부위를 직접·간접 자극하는 위험 동작을 추천에서 빼거나 뒤로 미룬다.
# 패턴은 영문 종목명(소문자) 부분일치. 회전근개에 오버헤드 프레스를 처방하던 갭을 메움.
_INJURY_RULES = [
    (("어깨", "회전근", "로테이터", "shoulder", "rotator"),
     {"어깨"},
     ("overhead press", "military press", "push press", "shoulder press",
      "thruster", "arnold press", "behind neck", "behind head",
      "behind the neck", "upright row", "snatch", "jerk",
      "clean and press", "overhead squat")),
    (("허리", "요추", "디스크", "lower back", "herniated"),
     set(),  # '등'은 상부등 → 부위 자체는 유지, 척추 부하 큰 동작만 제외
     ("deadlift", "good morning", "bent over", "bent-over", "barbell row",
      "t-bar", "power clean", "hang clean", "overhead squat", "back extension")),
    (("무릎", "슬개", "반월", "knee"),
     {"하체"},
     ("squat", "lunge", "leg press", "leg extension", "jump", "pistol",
      "step-up", "step up", "sissy")),
    (("팔꿈치", "elbow", "tennis"),
     set(),
     ("skullcrusher", "skull crusher", "lying triceps extension",
      "pushdown", "close-grip", "close grip", "dip")),
    (("손목", "wrist"),
     set(),
     ("front squat", "power clean", "hang clean", "snatch", "wrist")),
]

# 컴파운드 우선 정렬에 쓰는 장비 우선순위(낮을수록 우선)
_EQUIP_PRIORITY = {
    "바벨": 0, "덤벨": 1, "머신": 2, "케이블": 3,
    "케틀벨": 4, "맨몸": 5, "볼": 6, "밴드": 7,
}


def generate_routine(user_id: str, focus: str | None = None,
                     available_days: int = 3,
                     session_minutes: int | None = None) -> dict:
    """오늘/이번 주 루틴을 처방한다.

    focus: "가슴"|"하체"|... (None이면 일수 기반 분할에서 오늘 부위 자동 선택)
    반환: {split, exercises[], rationale}
    """
    profile = _load_profile(user_id)
    history = _recent_workouts(user_id)

    split_label, targets = _decide_split(available_days, focus, history)
    exercises = _build_exercises(targets, history, profile, session_minutes)
    rationale = _rationale(user_id, profile, split_label, exercises)

    return {"split": split_label, "exercises": exercises, "rationale": rationale}


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


def _normalize_focus(focus: str | None) -> str | None:
    """focus를 한글 정규 부위로 매핑. 인식 불가/미지정이면 None."""
    if not focus:
        return None
    raw = focus.strip()
    if raw in _FOCUS_TARGETS:          # 이미 정규 한글 부위
        return raw
    return _FOCUS_ALIASES.get(raw.lower())


def _decide_split(available_days: int, focus: str | None,
                  history) -> tuple[str, list[str]]:
    """일수/focus로 오늘 훈련할 (분할 라벨, 타깃 부위 목록)을 정한다."""
    norm = _normalize_focus(focus)
    if norm:
        return f"{norm} 집중", _FOCUS_TARGETS[norm]

    # focus 미지정이거나 인식 못한 값("lower body" 등) → 일수 기반 분할로 폴백.
    # ⚠️ 예전엔 미인식 focus를 그대로 target으로 써서 0건→빈 루틴이 나갔음. 절대 금지.
    days = max(1, min(6, available_days))
    plan = _SPLIT_PLANS[days]
    # 누적 기록 수로 순환 → 호출할수록 다음 분할일로 진행(결정론적)
    today_idx = len(history) % len(plan)
    return plan[today_idx]


def _injury_filters(injuries: str | None) -> tuple[set[str], list[str]]:
    """부상 텍스트에서 (후순위 부위, 제외할 영문 종목명 패턴)을 추출한다."""
    if not injuries:
        return set(), []
    text = injuries.lower()
    deprioritize: set[str] = set()
    blocked: list[str] = []
    for keywords, parts, name_pats in _INJURY_RULES:
        if any(k.lower() in text for k in keywords):
            deprioritize |= parts
            blocked.extend(name_pats)
    return deprioritize, blocked


def _name_blocked(name: str, patterns: list[str]) -> bool:
    low = name.lower()
    return any(p in low for p in patterns)


def _build_exercises(targets: list[str], history, profile,
                     session_minutes: int | None) -> list[dict]:
    """타깃 부위별 종목 선택 + 목표별 sets/reps + 점진적 과부하 + 부상 회피."""
    experience = normalize_experience(getattr(profile, "experience", None))
    goal = normalize_goal(getattr(profile, "goal", None))
    sets, reps = _sets_reps(goal, experience)
    last_idx = _last_weight_index(history)
    deprioritize, blocked = _injury_filters(getattr(profile, "injuries", None))

    # 다친 부위는 뒤로 미룬다(완전 제외하면 빈 루틴 위험 → 순서만 낮춤)
    ordered = ([t for t in targets if t not in deprioritize]
               + [t for t in targets if t in deprioritize])

    # 세션 길이 → 총 종목 수(대략 12분/종목), 미지정 시 6종
    if session_minutes:
        total_cap = max(3, min(8, session_minutes // 12))
    else:
        total_cap = 6
    per_target = 2 if len(targets) <= 3 else 1

    result: list[dict] = []
    for part in ordered:
        # 부상 악화 동작(오버헤드 프레스 등)은 종목 후보에서 제외
        candidates = [ex for ex in _query_exercises(part, experience)
                      if not _name_blocked(ex["name"], blocked)]
        for ex in candidates[:per_target]:
            if len(result) >= total_cap:
                return result
            result.append({
                "exercise": ex["name"],            # 영문(출력 시 한글화)
                "target": part,
                "sets": sets,
                "reps": reps,
                "target_load": _progress(ex["name"], last_idx, part),
                "form_cues": ex["form_cues"] or [],
            })
    return result


def _query_exercises(part: str, experience: str | None) -> list[dict]:
    """부위별 종목을 경력 필터 + 컴파운드 우선으로 정렬해 반환한다."""
    session = SessionLocal()
    try:
        rows = (session.query(ExerciseLibrary)
                .filter(ExerciseLibrary.target == part).all())
        # 초보는 휴리스틱 난이도 '초보' 종목만(없으면 전체로 폴백)
        if experience == "초보":
            beginner = [r for r in rows if r.difficulty == "초보"]
            rows = beginner or rows
        items = [{
            "name": r.name,
            "form_cues": r.form_cues,
            "equipment": r.equipment,
            "secondary": r.secondary or [],
        } for r in rows]
    finally:
        session.close()

    # 정렬 우선순위:
    # 1) 비(非)기술 동작 우선 — 올림픽 리프트(클린·스내치·저크)는 기술 난도가 높고
    #    데이터 태깅도 부정확(예: clean and press가 '하체')해서 일반 루틴 선두로 부적절 → 뒤로
    # 2) 정석 장비(바벨>덤벨>…) 우선
    # 3) 같은 조건이면 다관절(보조근 많음) 우선 → 컴파운드가 앞으로
    items.sort(key=lambda it: (
        _is_technical_lift(it["name"]),
        _EQUIP_PRIORITY.get(it["equipment"], 9),
        -len(it["secondary"]),
        it["name"],
    ))
    return items


# 일반 처방에서 선두에 두기엔 기술 난도가 높은 올림픽/파워 리프트 패턴
_TECHNICAL_LIFTS = ("clean", "snatch", "jerk", "thruster", "muscle-up", "muscle up")


def _is_technical_lift(name: str) -> int:
    low = name.lower()
    return 1 if any(p in low for p in _TECHNICAL_LIFTS) else 0


def _sets_reps(goal: str | None, experience: str | None) -> tuple[int, int]:
    """목표별 세트×반복 처방. 초보는 세트 수를 한 단계 낮춘다."""
    table = {
        "증량": (4, 8),     # 근비대·근력
        "감량": (3, 15),    # 고반복 대사
        "유지": (3, 12),
    }
    sets, reps = table.get(goal, (3, 12))
    if experience == "초보":
        sets = max(2, sets - 1)
    return sets, reps


def _last_weight_index(history) -> dict[str, float]:
    """최근 기록에서 종목별 가장 최근 무게를 모은다(정규 한글명 기준).

    로그 종목명은 parse_workout가 이미 정규화하지만, 별칭/영문 원문이 섞여도
    같은 공간(정규 한글)으로 모으도록 normalize_exercise를 한 번 더 태운다.
    """
    idx: dict[str, float] = {}
    for log in history:  # history는 date desc → 먼저 본 게 최신
        for entry in (log.parsed or []):
            ex, w = entry.get("exercise"), entry.get("weight")
            if ex and w is not None:
                key = normalize_exercise(ex)
                if key not in idx:
                    idx[key] = w
    return idx


def _progress(exercise_name: str, last_idx: dict[str, float],
              part: str) -> float | None:
    """직전 무게가 있으면 점진적 과부하 제안 중량을 계산한다.

    처방 종목은 라이브러리 영문명, 로그(last_idx)는 정규 한글명이라
    비교 전 영문 → 정규 한글로 변환해 같은 공간에서 매칭한다(끊김 A 제거, 이슈 #13).
    큐레이션된 28종 대표만 변환되고, 매핑 안 된 종목은 None(회귀 없음).
    """
    ko = lib_to_ko_canon(exercise_name)
    last = last_idx.get(ko) if ko is not None else None
    if last is None:                       # 브리지 미스 시 이름 직접 일치로 폴백
        last = last_idx.get(exercise_name)
    if last is None:
        return None
    increment = 5.0 if part == "하체" else 2.5
    return round(last + increment, 1)


def _rationale(user_id: str, profile, split_label: str,
               exercises: list[dict]) -> str:
    """profile.goal + 볼륨 추세로 처방 근거 한 문장(페르소나 중립)."""
    goal = normalize_goal(getattr(profile, "goal", None))
    goal_phrase = {
        "증량": "근비대 중심으로 볼륨을 쌓는",
        "감량": "고반복으로 소모를 높이는",
        "유지": "균형 있게 컨디션을 유지하는",
    }.get(goal, "기본기를 다지는")

    since = datetime.now().date() - timedelta(days=30)
    trend = _trend_volume(user_id, since)
    if trend.get("flag") == "insufficient_data":
        trend_phrase = "기록이 더 쌓이면 처방이 정밀해집니다"
    else:
        trend_phrase = {
            "up": "최근 볼륨이 잘 오르고 있어 과부하 흐름을 이어갑니다",
            "down": "최근 볼륨이 줄어 회복을 고려해 구성했습니다",
            "flat": "최근 볼륨이 정체라 세트·자극에 변화를 줬습니다",
        }.get(trend.get("direction"), "기록이 더 쌓이면 처방이 정밀해집니다")

    msg = (f"오늘은 {split_label} — {goal_phrase} 방향으로 "
           f"{len(exercises)}종 구성했어요. {trend_phrase}.")
    if getattr(profile, "injuries", None):
        msg += " 부상 이력을 반영해 해당 부위에 무리가 가는 동작은 빼고, 무게는 보수적으로 잡으세요."
    return msg


def _form_cues(exercise_name: str) -> list[str]:
    """종목명으로 form_cues(영문 단계) 조회. (보조 헬퍼)"""
    session = SessionLocal()
    try:
        ex = (session.query(ExerciseLibrary)
              .filter(ExerciseLibrary.name == exercise_name).first())
        return ex.form_cues if ex and ex.form_cues else []
    finally:
        session.close()
