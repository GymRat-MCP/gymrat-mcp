"""운동 루틴 처방 — 목표/이력 기반, 점진적 과부하 자동 반영

결정론적 룰 기반(LLM 호출 X)이라 안정성 점수에 유리.
form_cues는 exercise_library에서 가져옴(영문 단계) → 출력 시 호스트 LLM이 한글화.
"""
import re
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from db.session import SessionLocal
from db.models import ExerciseLibrary, WorkoutLog, User, Program
from tools.analysis import _trend_volume
from tools.persona import (
    DEFAULT_PERSONA,
    apply_persona,
    normalize_persona,
    persona_response_fields,
)
from tools.profile import normalize_goal, normalize_experience
from tools.workout_parser import normalize_exercise
from tools.exercise_map import (
    lib_to_ko_canon, log_name_to_part, movement_pattern, exercise_role,
    KO_CANON_TO_LIB,
)

_WEEKLY_SET_TARGET = 10   # 부위별 주당 최소 세트 랜드마크(하한, #15-2)


# ── 분할(split) 정의 ───────────────────────────────────────
# 부위 그룹 (ExerciseLibrary.target 한글 부위명 기준)
_PUSH = ["가슴", "어깨", "삼두"]
_PULL = ["등", "이두", "전완"]
# 보조 부위 — 메인 부위와 함께 처방될 땐 1종만(종아리·코어가 하체 같은
# 메인 볼륨을 밀어내지 않도록). 이 부위만 단독으로 요청되면 정상 개수로 처방.
_ACCESSORY_PARTS = {"종아리", "전완", "코어"}

# 근육 크기 순위(작을수록 먼저) — 세션 내 종목 정렬에 사용. 대근육 컴파운드를
# 앞에, 소근육 고립을 뒤로 두는 표준 순서. 삼두 고립이 벤치보다 앞서던 문제 교정.
_MUSCLE_SIZE_RANK = {
    "하체": 0, "등": 1, "가슴": 2, "어깨": 3,
    "삼두": 4, "이두": 4, "전완": 5, "종아리": 5, "코어": 5,
}

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

# 한국형 부위별(브로) 분할 — style="부위별"일 때. 하루 한(두) 부위에 집중.
# 하루 한 부위면 종목이 충분히(4~5종) 나오게 _distribute가 슬롯을 몰아준다.
_SPLIT_PLANS_BODYPART = {
    1: [("전신", _FULL)],
    2: [("상체", _UPPER), ("하체", _LOWER)],
    3: [("가슴·삼두", ["가슴", "삼두"]),
        ("등·이두", ["등", "이두"]),
        ("하체·어깨", ["하체", "어깨", "종아리"])],
    4: [("가슴", ["가슴"]), ("등", ["등"]),
        ("어깨·팔", ["어깨", "이두", "삼두"]), ("하체", _LOWER)],
    5: [("가슴", ["가슴"]), ("등", ["등"]), ("어깨", ["어깨"]),
        ("하체", _LOWER), ("팔", ["이두", "삼두", "전완"])],
    6: [("가슴", ["가슴"]), ("등", ["등"]), ("어깨", ["어깨"]),
        ("하체", _LOWER), ("팔", ["이두", "삼두", "전완"]),
        ("약점(코어·종아리)", ["코어", "종아리"])],
}

# 커스텀/day 지정 정규화가 다루는 유효 부위(= ExerciseLibrary.target 한글 부위).
_VALID_PARTS = {"가슴", "등", "어깨", "하체", "삼두", "이두", "전완", "종아리", "코어"}

# 부위 표면형(별칭·한자어) → 정규 부위. 긴 것 먼저 매칭(그리디 분해)하도록 길이 desc 정렬.
# "팔"은 특수 토큰으로 이두·삼두·전완으로 전개한다.
_ARM_PARTS = ["이두", "삼두", "전완"]
_PART_SURFACES = sorted([
    ("가슴", "가슴"), ("흉근", "가슴"),
    ("등", "등"), ("광배", "등"),
    ("어깨", "어깨"), ("삼각근", "어깨"), ("삼각", "어깨"),
    ("하체", "하체"), ("다리", "하체"), ("허벅지", "하체"),
    ("둔근", "하체"), ("엉덩이", "하체"), ("햄스트링", "하체"),
    ("삼두", "삼두"), ("이두", "이두"), ("전완", "전완"),
    ("종아리", "종아리"), ("카프", "종아리"),
    ("코어", "코어"), ("복근", "코어"), ("복부", "코어"),
    ("팔", "팔"),
], key=lambda s: -len(s[0]))

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
                     session_minutes: int | None = None,
                     day: str | None = None) -> dict:
    """오늘/이번 주 루틴을 처방한다.

    focus: "가슴"|"하체"|... (None이면 분할에서 오늘 부위 자동 선택 = recency)
    day: 명시 day 지정("2일차"/"등날") — 커스텀/프리셋 분할에서 해당 날 선택.
    반환: {split, exercises[], rationale}
    """
    profile = _load_profile(user_id)
    history = _recent_workouts(user_id)
    # 명시 일수(profile.training_days)가 있으면 그걸로 프로그램을 재설정(Phase C).
    training_days = getattr(profile, "training_days", None)
    program = _get_or_create_program(user_id, available_days,
                                     override_days=training_days)   # 주기화(#15)
    week, program_deload = _program_state(program)
    trend = _volume_trend(user_id)          # 분석 결과를 처방에 먹인다(#14)
    deload = _is_deload(trend) or program_deload   # 추세 or N주차 → 회복 주간

    # 메소사이클 볼륨 램프(Phase D): 디로드 직전 축적 주간에 세트 +1(피크).
    every = program.deload_every or 4
    volume_boost = 1 if (not deload and week % every == every - 1) else 0

    days = program.split_type or training_days or available_days
    experience = normalize_experience(getattr(profile, "experience", None))
    split_label, targets = _decide_split(
        days, focus, history,
        custom_split=getattr(profile, "custom_split", None),
        split_style=getattr(profile, "split_style", None),
        experience=experience, day=day)
    recent_parts = _recently_trained_parts(history)   # 48h 내 자극 부위 후순위(#15-2)
    exercises = _build_exercises(targets, history, profile, session_minutes,
                                 trend, recent_parts, deload, volume_boost,
                                 focus_part=_normalize_focus(focus))
    balance = _weekly_balance(history)                # 주간 부위별 세트량(#15-2)
    base_rationale = _rationale(
        profile, split_label, exercises, trend, deload, balance)
    persona = normalize_persona(getattr(profile, "persona", None) or DEFAULT_PERSONA)
    rationale = apply_persona(base_rationale, persona)
    # 종목 목록을 사용자 응답(assistant_message)에 함께 실어 호스트가 빠뜨리지 않게 한다.
    routine_text = _with_exercise_list(rationale, exercises)

    return {"split": split_label, "exercises": exercises, "rationale": rationale,
            "base_rationale": base_rationale,
            "persona": persona,
            "week": week, "deload": deload,
            "weekly_balance": balance,
            "pattern_mix": _pattern_mix(exercises),
            **persona_response_fields(
                persona, base_rationale, routine_text,
                fallback_field="rationale")}   # 하루 패턴 분포(#15-3)


def _volume_trend(user_id: str) -> dict:
    """최근 30일 볼륨 추세(direction/flag)를 가져온다(처방·rationale 공유)."""
    since = datetime.now().date() - timedelta(days=30)
    return _trend_volume(user_id, since)


def _is_deload(trend: dict) -> bool:
    """볼륨이 실제로 하락(down)할 때만 회복 주간(디로드).

    ⚠️ 정체(plateau)는 디로드가 아니다. 체중 PR은 볼륨(무게×세트×반복)을 거의
    안 올려서 발전 중인 리프터도 쉽게 '정체'로 잡히는데, 그때 무게를 ×0.9로 낮추면
    방금 신기록 세운 사람을 되레 후퇴시킨다(콘솔에서 반복되던 잘못된 '회복 주간').
    정체는 더블 프로그레션(_progress)이 렙으로 밀고, 계획된 디로드는 프로그램
    N주차(_program_state)가 담당한다.
    """
    return trend.get("direction") == "down"


# ── 주기화 프로그램 상태 (#15-1) ───────────────────────────
def _get_or_create_program(user_id: str, available_days: int,
                           override_days: int | None = None):
    """유저의 활성 프로그램을 읽거나(없으면) 오늘 시작으로 생성한다.

    세션 종료 후에도 안전하게 쓰도록 필요한 필드만 담은 값 객체를 반환한다.
    override_days(프로필의 training_days 등 '명시적' 일수)가 있고 기존 프로그램과
    다르면 갱신한다(자연어 "이제 주 3일만 해" → 다음 처방부터 반영, Phase C).
    ⚠️ available_days는 기본값(3)이 있어 '호스트 미지정'과 구분이 안 되므로 절대
    기존 프로그램을 덮어쓰지 않는다. 오직 override_days(명시 신호)만 재설정한다.
    """
    days = max(1, min(6, override_days or available_days))
    session = SessionLocal()
    try:
        prog = (session.query(Program)
                .filter(Program.user_id == user_id).first())
        if prog is None:
            prog = Program(user_id=user_id, split_type=days,
                           started_at=datetime.now().date(),
                           deload_every=4, week_index=0)
            session.add(prog)
            session.commit()
        elif override_days is not None:
            d = max(1, min(6, override_days))
            if prog.split_type != d:
                prog.split_type = d
                session.commit()
        return SimpleNamespace(split_type=prog.split_type,
                               started_at=prog.started_at,
                               deload_every=prog.deload_every or 4)
    finally:
        session.close()


def _program_state(program) -> tuple[int, bool]:
    """(현재 주차[1-base], 프로그램 디로드 여부)를 시작일 기준으로 파생한다."""
    elapsed = (datetime.now().date() - program.started_at).days
    week = elapsed // 7 + 1
    every = program.deload_every or 4
    return week, (week % every == 0)   # every의 배수 주차 = 자동 디로드


# ── 회복/빈도 인지 (#15-2) ─────────────────────────────────
def _recently_trained_parts(history, within_days: int = 2) -> set[str]:
    """최근 within_days일(≈48h) 내 로그에서 자극한 부위 집합."""
    today = datetime.now().date()
    parts: set[str] = set()
    for log in history:
        d = getattr(log, "date", None)
        if d is None or (today - d).days >= within_days:
            continue
        for entry in (log.parsed or []):
            p = log_name_to_part(entry.get("exercise"))
            if p:
                parts.add(p)
    return parts


def _weekly_balance(history, within_days: int = 7) -> dict[str, int]:
    """최근 within_days일 부위별 총 세트량(주간 볼륨 균형 리포트)."""
    today = datetime.now().date()
    bal: dict[str, int] = {}
    for log in history:
        d = getattr(log, "date", None)
        if d is None or (today - d).days >= within_days:
            continue
        for entry in (log.parsed or []):
            p = log_name_to_part(entry.get("exercise"))
            s = entry.get("sets") or 0
            if p and s:
                bal[p] = bal.get(p, 0) + s
    return bal


def _stalled_exercises(history, window: int = 3) -> set[str]:
    """최근 window회 연속 같은 무게로 정체된 종목(정규 한글명) 집합(Phase D).

    로그는 date desc라 종목별 최근 무게를 앞에서부터 모은다. 최근 window회가
    모두 같은 무게면 진전이 멈춘 것 → 처방에서 백오프로 러닝 스타트를 준다.
    """
    series: dict[str, list[float]] = {}
    for log in history:                 # 최신 → 과거 순
        for entry in (log.parsed or []):
            ex, w = entry.get("exercise"), entry.get("weight")
            if ex and w is not None:
                series.setdefault(normalize_exercise(ex), []).append(w)
    stalled = set()
    for ko, weights in series.items():
        recent = weights[:window]
        if len(recent) >= window and len(set(recent)) == 1:
            stalled.add(ko)
    return stalled


# 경력별 주당 부위 세트 랜드마크(볼륨 리포트 하한). 초보는 적게, 고급은 많이.
_WEEKLY_TARGET_BY_EXP = {"초보": 8, "중급": 10, "고급": 14}


def _weekly_target(experience: str | None) -> int:
    """경력별 주당 부위 세트 하한(랜드마크). 미지정이면 중급 기준."""
    return _WEEKLY_TARGET_BY_EXP.get(experience, _WEEKLY_SET_TARGET)


def _pattern_mix(exercises: list[dict]) -> dict[str, int]:
    """오늘 처방의 움직임 패턴 분포(#15-3)."""
    mix: dict[str, int] = {}
    for e in exercises:
        p = e.get("pattern", "기타")
        mix[p] = mix.get(p, 0) + 1
    return mix


def _with_exercise_list(rationale: str, exercises: list[dict]) -> str:
    """rationale 뒤에 '오늘의 종목' 목록을 붙인다(호스트가 종목을 빠뜨리지 않게).

    exercises는 구조화 배열이라 호스트가 rationale만 보고 종목을 안 보여주는 일이
    잦았다. 무게×세트×반복을 사람이 읽는 목록으로 assistant_message에 함께 실어
    '왜 안 보여줘?' 되묻는 문제를 없앤다. 종목명은 영문(출력 시 호스트가 한글화).
    """
    if not exercises:
        return rationale
    lines = []
    for i, e in enumerate(exercises, 1):
        load = e.get("target_load")
        load_s = f" · 목표 {load:g}kg" if load else ""
        lines.append(f"{i}. {e['exercise']} {e['sets']}×{e['reps']}{load_s}")
    return f"{rationale}\n\n오늘의 종목:\n" + "\n".join(lines)


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


# ── 부위명 정규화(커스텀 분할·day 지정 입력용) ──────────────
def _decompose_part(token: str) -> list[str]:
    """부위 토큰 하나를 정규 부위 목록으로 분해한다.

    - "가슴" → ["가슴"], "다리" → ["하체"](별칭)
    - "팔" → ["이두","삼두","전완"](전개)
    - "가슴삼두"처럼 붙여 쓴 것 → ["가슴","삼두"](그리디 최장 매칭 분해)
    인식 못한 조각은 버린다(빈 루틴/잘못된 부위 방어).
    """
    tok = token.strip()
    if not tok:
        return []
    if tok in _VALID_PARTS:
        return [tok]
    out: list[str] = []
    i = 0
    matched_any = False
    while i < len(tok):
        for surface, canon in _PART_SURFACES:
            if tok.startswith(surface, i):
                if canon == "팔":
                    for p in _ARM_PARTS:
                        if p not in out:
                            out.append(p)
                elif canon not in out:
                    out.append(canon)
                i += len(surface)
                matched_any = True
                break
        else:
            i += 1        # 미인식 문자 건너뜀
    return out if matched_any else []


def _normalize_parts(raw_parts) -> list[str]:
    """자유 입력(리스트/문자열)을 정규 부위 목록으로. 중복·미인식 제거, 순서 보존."""
    if isinstance(raw_parts, str):
        raw_parts = [raw_parts]
    out: list[str] = []
    for item in (raw_parts or []):
        for tok in re.split(r"[,/·+&\s]+", str(item)):
            for p in _decompose_part(tok):
                if p not in out:
                    out.append(p)
    return out


def _custom_plan(custom_split) -> list[tuple[str, list[str]]] | None:
    """User.custom_split(dict) → [(label, parts)] 플랜. 유효 day 없으면 None."""
    if not custom_split:
        return None
    days = custom_split.get("days") if isinstance(custom_split, dict) else None
    if not days:
        return None
    plan: list[tuple[str, list[str]]] = []
    for d in days:
        parts = _normalize_parts(d.get("parts")) if isinstance(d, dict) else []
        if not parts:
            continue
        label = (d.get("label") if isinstance(d, dict) else None) or "·".join(parts)
        plan.append((label, parts))
    return plan or None


def _resolve_plan(split_style: str | None, days: int,
                  experience: str | None) -> list[tuple[str, list[str]]]:
    """(스타일, 일수, 경력)으로 프리셋 플랜을 고른다.

    "PPL"=기존 상하체/PPL, "부위별"=한국형 브로 분할, "자동"/미설정=기존 기본
    (하위호환: 예전 동작 그대로 PPL/상하체). 부위별 권장은 rationale nudge로만.
    """
    days = max(1, min(6, days))
    if split_style == "부위별":
        return _SPLIT_PLANS_BODYPART[days]
    return _SPLIT_PLANS[days]


def _part_last_date(history) -> dict[str, "object"]:
    """부위별 '마지막으로 훈련된 날짜'. history는 date desc라 처음 본 게 최신."""
    last: dict = {}
    for log in history:
        d = getattr(log, "date", None)
        if d is None:
            continue
        for entry in (log.parsed or []):
            p = log_name_to_part(entry.get("exercise"))
            if p and p not in last:
                last[p] = d
    return last


def _pick_today_by_recency(plan: list[tuple[str, list[str]]], history) -> int:
    """가장 오래 안 한 day를 오늘로 고른다(recency). 동률이면 플랜 순서 우선.

    day의 '최근도' = 그 day parts 중 가장 최근에 훈련된 날짜(max). 한 번도 안 한
    부위는 date.min 취급 → 안 한 day가 먼저 선택된다. 신규 유저(전부 미훈련)는
    전 day 동률 → 1일차부터.
    """
    if not plan:
        return 0
    last = _part_last_date(history)
    floor = date.min
    best_idx, best_recency = 0, None
    for idx, (_label, parts) in enumerate(plan):
        recency = max((last.get(p, floor) for p in parts), default=floor)
        if best_recency is None or recency < best_recency:
            best_idx, best_recency = idx, recency
    return best_idx


def _select_day_by_hint(plan: list[tuple[str, list[str]]],
                        day) -> tuple[str, list[str]] | None:
    """명시 day 지정("2일차"/"등날"/"어깨")을 플랜의 한 day로 해석."""
    s = str(day).strip()
    if not s:
        return None
    m = re.search(r"(\d+)", s)          # "2일차" → 인덱스
    if m:
        i = int(m.group(1))
        if 1 <= i <= len(plan):
            return plan[i - 1]
    for label, parts in plan:           # 라벨 부분일치
        if s and s in label:
            return label, parts
    hint = set(_normalize_parts([re.sub(r"(날|day|데이)$", "", s)]))
    if hint:
        for label, parts in plan:       # 부위 겹침(가장 앞 day)
            if hint & set(parts):
                return label, parts
    return None


def _decide_split(available_days: int, focus: str | None, history, *,
                  custom_split=None, split_style: str | None = None,
                  experience: str | None = None,
                  day=None) -> tuple[str, list[str]]:
    """오늘 훈련할 (분할 라벨, 타깃 부위 목록)을 정한다.

    우선순위: 1) 명시 focus(단일 부위) 2) 명시 day 지정 3) 커스텀 분할(recency)
    4) 프리셋(스타일·일수 → recency) 5) 폴백(프리셋 1일차).
    """
    norm = _normalize_focus(focus)
    if norm:
        return f"{norm} 집중", _FOCUS_TARGETS[norm]

    # focus 미지정이거나 인식 못한 값("lower body" 등) → 분할 플랜으로 폴백.
    # ⚠️ 예전엔 미인식 focus를 그대로 target으로 써서 0건→빈 루틴이 나갔음. 절대 금지.
    days = max(1, min(6, available_days))
    plan = _custom_plan(custom_split) or _resolve_plan(split_style, days, experience)

    if day is not None:                          # 명시 day 지정
        picked = _select_day_by_hint(plan, day)
        if picked:
            return picked

    return plan[_pick_today_by_recency(plan, history)]   # 오늘의 날 = recency


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


# ── 개인화: 보유 장비 필터 · 선호 제외 (Phase C) ────────────
# 장비 별칭 → 라이브러리 equipment 정규값(DB target과 일치).
_EQUIP_ALIASES = {
    "바벨": "바벨", "barbell": "바벨",
    "덤벨": "덤벨", "dumbbell": "덤벨",
    "머신": "머신", "machine": "머신",
    "케이블": "케이블", "cable": "케이블",
    "케틀벨": "케틀벨", "kettlebell": "케틀벨",
    "맨몸": "맨몸", "bodyweight": "맨몸", "body weight": "맨몸", "bw": "맨몸",
    "밴드": "밴드", "band": "밴드",
    "볼": "볼", "ball": "볼",
}
# 이 값이 들어오면 "장비 다 있음" → 필터 안 함.
_NO_EQUIP_FILTER = {"풀짐", "헬스장", "짐", "gym", "full", "전체", "다", "all", "없음"}


def _allowed_equipment(available: str | list | None) -> set[str] | None:
    """available_equipment(자유 텍스트/리스트)를 허용 장비 집합으로 파싱한다.

    None/미인식/"풀짐"이면 None(필터 안 함). 뭐라도 골랐으면 빈 루틴 방지를
    위해 맨몸을 항상 허용에 포함.
    """
    if not available:
        return None
    tokens = (re.split(r"[,/·\s]+", available) if isinstance(available, str)
              else list(available))
    allowed: set[str] = set()
    for t in tokens:
        raw = str(t).strip()
        low = raw.lower()
        if not raw:
            continue
        if raw in _NO_EQUIP_FILTER or low in _NO_EQUIP_FILTER:
            return None
        canon = _EQUIP_ALIASES.get(raw) or _EQUIP_ALIASES.get(low)
        if canon:
            allowed.add(canon)
    if allowed:
        allowed.add("맨몸")        # 맨몸은 언제나 가능(빈 루틴 방지)
    return allowed or None


def _disliked_patterns(disliked: str | list | None) -> list[str]:
    """disliked_exercises → 차단할 영문 종목명 패턴(부상 blocked와 같은 경로).

    한글 정규명은 KO_CANON_TO_LIB로 영문 대표명까지 확장해 라이브러리 종목과
    매칭되게 한다(예: '레그익스텐션' → 'lever leg extension').
    """
    if not disliked:
        return []
    items = (re.split(r"[,/·]+", disliked) if isinstance(disliked, str)
             else list(disliked))
    pats: list[str] = []
    for d in items:
        d = str(d).strip()
        if not d:
            continue
        pats.append(d.lower())
        lib = KO_CANON_TO_LIB.get(normalize_exercise(d))
        if lib:
            pats.append(lib.lower())
    return pats


# 부위 수별 슬롯 패턴(1~3부위). 4부위 이상은 각 1종.
# 2·3부위는 기존 동작(각 2종)과 정합 — 회귀 테스트 개수 불변. 1부위는 몰아줘서
# '가슴날=가슴 4~5종'이 되게 한다. 총합은 total_cap이 상한으로 최종 클램프.
_SLOT_PATTERN = {1: [5], 2: [3, 2], 3: [2, 2, 2]}


def _distribute(total_cap: int, parts: list[str]) -> dict[str, int]:
    """총 종목 수(total_cap)를 그 날 부위들에 분배한다.

    1부위→그 부위에 몰아(≤5), 2부위→3+2, 3부위→각 2, 4+부위→각 1(남으면 주
    부위부터 +1). 실제 개수는 후보 종목 수와 total_cap 루프로 최종 결정된다.
    """
    n = len(parts)
    if n == 0:
        return {}
    pattern = _SLOT_PATTERN.get(n)
    if pattern is None:                    # 4부위 이상 → 각 1, 잔여는 앞 부위부터
        base = [1] * n
        extra = max(0, total_cap - n)
        for i in range(min(extra, n)):
            base[i] += 1
        pattern = base
    slots = {p: min(pattern[i], total_cap) for i, p in enumerate(parts)}
    return slots


def _build_exercises(targets: list[str], history, profile,
                     session_minutes: int | None,
                     trend: dict | None = None,
                     recent_parts: set[str] | None = None,
                     deload: bool | None = None,
                     volume_boost: int = 0,
                     focus_part: str | None = None) -> list[dict]:
    """타깃 부위별 종목 선택 + 목표별 sets/reps + 점진적 과부하 + 부상/회복 회피.

    - 볼륨 추세를 읽어 디로드/과부하 분기(#14): 하락·정체면 세트 -1 + 무게 디로드.
      deload가 명시되면 그 값을 쓴다(프로그램 N주차 디로드 포함, #15).
    - recent_parts(최근 48h 자극 부위)는 부상 부위처럼 뒤로 미룬다(#15-2).
    """
    experience = normalize_experience(getattr(profile, "experience", None))
    goal = normalize_goal(getattr(profile, "goal", None))
    if deload is None:
        deload = _is_deload(trend or {})
    last_idx = _last_weight_index(history)
    stalled = _stalled_exercises(history)   # 종목 단위 정체 → 백오프(Phase D)
    deprioritize, blocked = _injury_filters(getattr(profile, "injuries", None))
    deprioritize |= (recent_parts or set())   # 48h 내 자극 부위도 후순위
    # 개인화(Phase C): 싫어하는 종목은 부상처럼 차단, 보유 장비로 후보 필터
    blocked = blocked + _disliked_patterns(
        getattr(profile, "disliked_exercises", None))
    allowed_equip = _allowed_equipment(
        getattr(profile, "available_equipment", None))

    # 정렬 순서: 다친/최근 자극 부위는 뒤로, 보조 부위(종아리·코어)도 메인 뒤로.
    # (완전 제외하면 빈 루틴 위험 → 순서·개수만 낮춤). sorted는 안정 정렬이라
    # 같은 키 안에선 원래 target 순서를 보존한다.
    # 명시 focus 부위는 최근 자극(recency)으로 후순위 밀지 않는다 — 사용자가 콕
    # 집어 요청했는데 오늘 이미 했다고 뒤로 밀면 엉뚱한 보조 부위가 앞선다.
    ordered = sorted(targets,
                     key=lambda t: (t != focus_part and t in deprioritize,
                                    t in _ACCESSORY_PARTS))

    # 세션 길이 → 총 종목 수(대략 12분/종목), 미지정 시 6종
    if session_minutes:
        total_cap = max(3, min(8, session_minutes // 12))
    else:
        total_cap = 6

    # 부위 수에 따라 total_cap을 부위별 슬롯으로 분배(⭐ 5분할 '가슴날'이 2종만
    # 나오던 문제 해결). 보조 부위는 메인과 함께 나올 때 1종으로 캡.
    has_primary = any(t not in _ACCESSORY_PARTS for t in targets)
    slots = _distribute(total_cap, ordered)
    if has_primary:
        for p in list(slots):
            if p in _ACCESSORY_PARTS:
                slots[p] = min(slots[p], 1)

    def _slots(part: str) -> int:
        return slots.get(part, 1)

    offset = len(history)   # 기록이 쌓일수록 보조 종목이 순환(세션 간 다양성)
    result: list[dict] = []
    for part in ordered:
        if len(result) >= total_cap:
            break
        # 부상 악화 동작(오버헤드 프레스 등)은 종목 후보에서 제외
        candidates = [ex for ex in _query_exercises(part, experience, allowed_equip)
                      if not _name_blocked(ex["name"], blocked)]
        for ex in _pick_complementary(candidates, _slots(part), offset):
            if len(result) >= total_cap:
                break
            # 종목 역할별 처방 — 컴파운드/고립에 다른 sets·reps·휴식·강도(Phase A)
            role = exercise_role(ex["name"], ex["secondary"])
            sets, reps, rest_sec, intensity = _prescribe(
                role, goal, experience, deload, volume_boost)
            load, ex_reps = _progress(ex["name"], last_idx, part, reps,
                                      deload, stalled)
            # P3: 오늘의 구체적 목표(무게×반복) + 처방 노트 표면화
            prescription = _next_target(ex["name"], last_idx, part, sets, reps,
                                        load, ex_reps, deload, stalled)
            result.append({
                "exercise": ex["name"],            # 영문(출력 시 한글화)
                "target": part,
                "role": role,                      # compound|isolation
                "pattern": movement_pattern(ex["name"]),   # 밀기/당기기/... (#15-3)
                "sets": sets,
                "reps": ex_reps,                   # 더블 프로그레션 시 렙 +1 될 수 있음
                "rest_sec": rest_sec,              # 세트 간 휴식(Phase A)
                "intensity": intensity,            # 목표 강도(RPE, Phase A)
                "target_load": load,
                "prescription": prescription,      # P3: {weight,reps,sets,scheme,note}
                "form_cues": ex["form_cues"] or [],
            })
    # 대근육/컴파운드 먼저: 명시 focus면 그 부위를 앞으로, 그다음 근육 크기순,
    # 같은 조건이면 컴파운드를 고립보다 앞에 둔다(삼두 고립이 벤치보다 앞서던 문제 교정).
    result.sort(key=lambda e: (
        focus_part is not None and e["target"] != focus_part,
        _MUSCLE_SIZE_RANK.get(e["target"], 3),
        0 if e["role"] == "compound" else 1,
    ))
    return result


def _query_exercises(part: str, experience: str | None,
                     allowed_equipment: set[str] | None = None) -> list[dict]:
    """부위별 종목을 경력·장비 필터 + 컴파운드 우선으로 정렬해 반환한다."""
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

    # 보유 장비 필터(Phase C): 가진 장비 종목만. 이 부위가 통째로 비면
    # 맨몸으로, 그래도 없으면 전체로 폴백(빈 루틴 금지).
    if allowed_equipment:
        filtered = [it for it in items if it["equipment"] in allowed_equipment]
        items = filtered or [it for it in items if it["equipment"] == "맨몸"] or items

    # 정렬 우선순위:
    # 1) 비(非)기술 동작 우선 — 올림픽 리프트(클린·스내치·저크)는 기술 난도가 높고
    #    데이터 태깅도 부정확(예: clean and press가 '하체')해서 일반 루틴 선두로 부적절 → 뒤로
    # 2) 큐레이션된 주류 종목 우선 — 사람들이 실제 쓰는 대표 28종(exercise_map)을
    #    앞으로. 데이터셋엔 "barbell full squat (back pov)"처럼 near-중복 변형이
    #    많아 알파벳 tiebreak만으론 비주류 변형이 상단에 뜨는 문제를 막는다.
    # 3) 중복/비주류 변형 태그((back pov)·(female)·v.2 등)는 후순위
    # 4) 정석 장비(바벨>덤벨>…) 우선
    # 5) 같은 조건이면 다관절(보조근 많음) 우선 → 컴파운드가 앞으로
    items.sort(key=lambda it: (
        _is_technical_lift(it["name"]),
        _is_preferred(it["name"]),
        _is_junk_variant(it["name"]),
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


# 큐레이션된 주류 종목명(사용자가 실제 로그하는 대표 28종) → 선택 시 최우선.
_PREFERRED_NAMES = {v.lower() for v in KO_CANON_TO_LIB.values()}

# 데이터셋에 흔한 near-중복/비주류 변형 태그 — 상단 노출 방지용 후순위 마커.
_JUNK_MARKERS = ("pov", "female", "male", "(1)", "(2)", "(3)",
                 "v. 2", "v.2", "version", "wrong")


def _is_preferred(name: str) -> int:
    """큐레이션된 주류 종목이면 0(우선), 아니면 1."""
    return 0 if name.lower() in _PREFERRED_NAMES else 1


def _is_junk_variant(name: str) -> int:
    """near-중복/비주류 변형 태그가 붙은 이름이면 1(후순위), 아니면 0."""
    low = name.lower()
    return 1 if any(m in low for m in _JUNK_MARKERS) else 0


# 로테이션은 상위 후보 안에서만 — 데이터셋 꼬리(비주류 변형 수백 개)까지 순환하면
# 세션이 지날수록 이상한 종목이 튀어나온다. 정렬 상단 주류 종목 안에서만 돌린다.
_ROTATION_WINDOW = 6


def _diversity_key(name: str) -> str:
    """종목 선택 다양성용 세분 패턴 키(Phase B).

    movement_pattern은 로우/랫풀다운을 둘 다 '당기기'로, 벤치/플라이를 둘 다
    '밀기'로 뭉갠다. 하루 안에서 상보적 종목(수직+수평 당기기, 프레스+플라이)을
    고르려면 더 잘게 나눠야 한다.
    """
    low = name.lower()
    if any(k in low for k in ("pulldown", "pull-down", "pull-up", "pullup",
                              "pull up", "chin-up", "chinup", "chin up")):
        return "수직당기기"
    if "row" in low:
        return "수평당기기"
    if any(k in low for k in ("overhead press", "shoulder press",
                              "military press")):
        return "수직밀기"
    if any(k in low for k in ("bench press", "chest press", "push-up",
                              "push up")):
        return "수평밀기"
    if any(k in low for k in ("fly", "flye", "crossover", "pec deck")):
        return "플라이"
    return movement_pattern(name)


def _pick_complementary(candidates: list[dict], count: int,
                        offset: int) -> list[dict]:
    """부위별 종목을 count개 고른다 — 대표 컴파운드(0순위)는 고정하고, 나머지
    슬롯은 (1)아직 안 쓴 움직임 패턴을 우선하고 (2)상위 주류 후보 안에서
    offset부터 순환해 채운다. → 로우 2종·프레스 2종 같은 중복 대신 상보적 조합
    (수직+수평 당기기 등)을, 그러면서 세션마다 보조 종목이 바뀌도록.
    """
    if count <= 0 or not candidates:
        return []
    picks = [candidates[0]]                   # 대표 컴파운드 고정(스쿼트 등)
    used = {_diversity_key(candidates[0]["name"])}
    pool = list(candidates[1:_ROTATION_WINDOW])   # 상위 주류 후보로 범위 제한
    rot = offset
    while len(picks) < count and pool:
        # 새 패턴 후보 우선 — 없으면 남은 풀에서 로테이션
        fresh = [c for c in pool if _diversity_key(c["name"]) not in used]
        src = fresh or pool
        pick = src[rot % len(src)]
        rot += 1
        picks.append(pick)
        used.add(_diversity_key(pick["name"]))
        pool = [c for c in pool if c is not pick]
    return picks


def _prescribe(role: str, goal: str | None, experience: str | None,
               deload: bool = False,
               volume_boost: int = 0) -> tuple[int, int, int, str]:
    """종목 역할별로 (세트, 목표반복, 휴식초, 강도문구)를 처방한다.

    핵심: 반복수는 **종목 역할**이 정한다 — 컴파운드는 저~중반복, 고립은 고반복.
    목표(goal)는 세트/강도 뉘앙스만 조절하지 반복수를 뒤집지 않는다.
    (구 버전의 "감량=고반복 15회"는 운동 상식 오류 — 체지방은 식단이 결정.)
    volume_boost는 메소사이클 축적 주간(디로드 직전 피크)에 세트를 얹는다(Phase D).
    """
    if role == "compound":
        reps = 6 if goal == "증량" else 8        # 저~중반복(근력·근비대)
        sets = 4 if goal == "증량" else 3
        rest, rpe = 150, "RPE 7~8 (마지막 2~3회는 힘들게)"
    else:                                          # isolation
        reps = 12 if goal == "증량" else 15       # 중~고반복(펌프·대사)
        sets = 3
        rest, rpe = 75, "RPE 8~9 (마지막 1~2회 남기고)"
    if experience == "초보":
        sets = max(2, sets - 1)                    # 초보는 볼륨 한 단계 낮춤
    if deload:
        sets = max(1, sets - 1)                    # 회복 주간: 세트↓
        rpe = "RPE 5~6 (가볍게, 회복 주간)"
    else:
        sets += max(0, volume_boost)               # 축적 주간: 세트↑(디로드 아닐 때만)
    return sets, reps, rest, rpe


def _last_weight_index(history) -> dict[str, dict]:
    """최근 기록에서 종목별 직전 세션(무게·세트·렙)을 모은다(정규 한글명 기준).

    로그 종목명은 parse_workout가 이미 정규화하지만, 별칭/영문 원문이 섞여도
    같은 공간(정규 한글)으로 모으도록 normalize_exercise를 한 번 더 태운다.
    더블 프로그레션(#14)이 직전 렙을 보게 무게뿐 아니라 세트·렙도 보관한다.
    """
    idx: dict[str, dict] = {}
    for log in history:  # history는 date desc → 먼저 본 게 최신
        for entry in (log.parsed or []):
            ex, w = entry.get("exercise"), entry.get("weight")
            if ex and w is not None:
                key = normalize_exercise(ex)
                if key not in idx:
                    idx[key] = {"weight": w,
                                "sets": entry.get("sets"),
                                "reps": entry.get("reps")}
    return idx


def _progress(exercise_name: str, last_idx: dict[str, dict],
              part: str, base_reps: int,
              deload: bool = False,
              stalled: set[str] | None = None) -> tuple[float | None, int]:
    """직전 기록으로 다음 처방 (target_load, reps)를 정한다.

    - 브리지(#13): 처방 영문명 → 정규 한글로 변환 후 last_idx 조회. 큐레이션 28종만
      매칭되고, 매핑/기록 없으면 (None, base_reps) — 첫 처방(회귀 없음).
    - 더블 프로그레션(#14): 직전에 목표 렙(base_reps) 상단을 채웠으면 무게↑,
      못 채웠으면 무게 유지 + 렙 +1.
    - 디로드 주간이면 무게 -10%(회복), 렙은 목표로 리셋.
    - 정체(Phase D): 최근 N회 같은 무게로 멈춘 종목은 -10% 백오프 후 렙 리셋 —
      플래토를 깨는 러닝 스타트(디로드와 별개로 종목 단위 발화).
    """
    ko = lib_to_ko_canon(exercise_name)
    last = last_idx.get(ko) if ko is not None else None
    if last is None:                       # 브리지 미스 시 이름 직접 일치로 폴백
        last = last_idx.get(exercise_name)
    if last is None:
        return None, base_reps
    w = last["weight"]
    if deload:
        return round(w * 0.9, 1), base_reps
    if stalled and ko in stalled:          # 종목 단위 정체 → 백오프로 러닝 스타트
        return round(w * 0.9, 1), base_reps
    increment = 5.0 if part == "하체" else 2.5
    last_reps = last.get("reps")
    if last_reps is None or last_reps >= base_reps:
        return round(w + increment, 1), base_reps   # 목표 렙 달성 → 무게↑
    return w, last_reps + 1                          # 미달 → 무게 유지, 렙 +1


def _fmt_kg(w: float | None) -> str:
    """무게를 사람이 읽는 문자열로. None(맨몸)은 '맨몸'."""
    if w is None:
        return "맨몸"
    return f"{w:g}kg"


def _next_target(exercise_name: str, last_idx: dict[str, dict], part: str,
                 sets: int, base_reps: int, load: float | None, ex_reps: int,
                 deload: bool, stalled: set[str] | None) -> dict:
    """P3: 오늘의 구체적 목표(무게×반복) + 사람이 읽는 처방 노트.

    `_progress`가 이미 계산한 (load, ex_reps)를 받아 '왜 이 수치인가'를
    직전 세션과 대비해 설명한다. 처방을 "종목 나열"에서 "몇 kg 몇 개"로
    표면화(출력 계약 강화)하는 게 핵심 — 룰 자체는 _progress가 소유.
    """
    # last_idx 조회 키: 브리지가 되면 ko, 안 되면 영문/원문 직접 매칭(_progress와 동일)
    ko = lib_to_ko_canon(exercise_name)
    key = ko if (ko is not None and ko in last_idx) else exercise_name
    last = last_idx.get(key)
    scheme = f"{sets}×{ex_reps}"
    target = {"weight": load, "reps": ex_reps, "sets": sets, "scheme": scheme}

    if last is None or load is None:       # 이력 없음 → 보수적 시작 안내
        target["note"] = (f"첫 기록이라 부담 없는 무게로 {ex_reps}회씩 폼부터 잡고, "
                          "다음 세션부터 조금씩 올려가요.")
        return target

    pw, pr = last.get("weight"), last.get("reps")
    prev_desc = _fmt_kg(pw) + (f" {pr}회" if pr else "")
    if deload:
        target["note"] = (f"회복 주간 — 지난 {prev_desc}에서 {_fmt_kg(load)}로 낮춰 "
                          f"{ex_reps}회, 폼·컨디션 회복에 집중해요.")
    elif stalled and key in stalled:
        target["note"] = (f"최근 {_fmt_kg(pw)}에서 정체 — {_fmt_kg(load)}로 한 발 "
                          "물러나 러닝 스타트 후 다시 올려요.")
    elif pw is not None and load > pw:
        target["note"] = (f"지난번 {prev_desc} 달성 → 오늘 {_fmt_kg(load)} {ex_reps}회 "
                          f"도전! (미달 시 {_fmt_kg(pw)}로 반복수부터 채워요)")
    elif ex_reps > (pr or 0):
        target["note"] = (f"지난번 {prev_desc} → 오늘 같은 {_fmt_kg(load)}로 {ex_reps}회 "
                          "목표 (반복수 늘리기)")
    else:
        target["note"] = f"{_fmt_kg(load)} {scheme}로 유지하며 자극의 질에 집중해요."
    return target


def _rationale(profile, split_label: str, exercises: list[dict],
               trend: dict, deload: bool, balance: dict | None = None) -> str:
    """profile.goal + 볼륨 추세로 처방 근거 한 문장(페르소나 중립).

    디로드 주간이면 회복 의도를 명시해 '분석이 처방을 바꿨다'를 드러낸다(#14).
    주간 부위 볼륨이 랜드마크에 못 미치면 보완 부위를 짚어준다(#15-2).
    """
    goal = normalize_goal(getattr(profile, "goal", None))
    goal_phrase = {
        "증량": "근비대 중심으로 볼륨을 쌓는",
        "감량": "고반복으로 소모를 높이는",
        "유지": "균형 있게 컨디션을 유지하는",
    }.get(goal, "기본기를 다지는")

    if trend.get("flag") == "insufficient_data":
        trend_phrase = "기록이 더 쌓이면 처방이 정밀해집니다"
    elif deload:
        trend_phrase = "최근 볼륨 흐름을 보고 이번 주는 세트·무게를 낮춘 회복 주간으로 구성했어요"
    else:
        trend_phrase = {
            "up": "최근 볼륨이 잘 오르고 있어 과부하 흐름을 이어갑니다",
            "down": "최근 볼륨이 줄어 회복을 고려해 구성했습니다",
            "flat": "최근 볼륨이 정체라 세트·자극에 변화를 줬습니다",
        }.get(trend.get("direction"), "기록이 더 쌓이면 처방이 정밀해집니다")

    msg = (f"오늘은 {split_label} — {goal_phrase} 방향으로 "
           f"{len(exercises)}종 구성했어요. {trend_phrase}.")
    target = _weekly_target(normalize_experience(getattr(profile, "experience", None)))
    low = sorted(p for p, s in (balance or {}).items() if s < target)
    if low:
        msg += f" 이번 주 {'·'.join(low)} 볼륨이 아직 적어 다음 세션에서 보완하면 좋아요."
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


# ── 커스텀 분할 저장/조회/해제 (Phase B) ────────────────────
def set_workout_split(user_id: str, days: list[dict]) -> dict:
    """유저의 커스텀 분할을 저장한다(수정도 전체 재전송 = edit_workout 패턴).

    days=[{"label"?, "parts":[..]}]. 부위명은 정규화("가슴삼두"→["가슴","삼두"],
    "다리"→["하체"]). 유효 부위가 하나도 없으면 저장하지 않고 에러를 돌려준다.
    """
    if not days or not isinstance(days, list):
        return {"updated": False, "error": "days must be a non-empty list"}
    normalized: list[dict] = []
    for i, d in enumerate(days, 1):
        parts = _normalize_parts(d.get("parts") if isinstance(d, dict) else d)
        if not parts:
            continue
        label = (d.get("label") if isinstance(d, dict) else None) or "·".join(parts)
        normalized.append({"label": label, "parts": parts})
    if not normalized:
        return {"updated": False,
                "error": "유효한 부위를 찾지 못했어요. 가슴/등/어깨/하체/이두/삼두/"
                         "전완/종아리/코어 중에서 지정해 주세요."}
    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        if not user:
            user = User(id=user_id)
            session.add(user)
        user.custom_split = {"days": normalized}
        session.commit()
        return {"updated": True, "user_id": user_id,
                "days": normalized, "day_count": len(normalized)}
    except Exception as e:
        session.rollback()
        return {"updated": False, "error": str(e)}
    finally:
        session.close()


def get_workout_split(user_id: str) -> dict:
    """현재 유효 분할을 반환한다 — 커스텀이 있으면 커스텀, 없으면 해석된 프리셋."""
    profile = _load_profile(user_id)
    custom = getattr(profile, "custom_split", None)
    plan = _custom_plan(custom)
    if plan:
        return {"source": "custom",
                "days": [{"label": lbl, "parts": parts} for lbl, parts in plan],
                "day_count": len(plan)}
    training_days = getattr(profile, "training_days", None) or 3
    style = getattr(profile, "split_style", None) or "자동"
    experience = normalize_experience(getattr(profile, "experience", None))
    preset = _resolve_plan(style, training_days, experience)
    return {"source": "preset", "split_style": style,
            "training_days": max(1, min(6, training_days)),
            "days": [{"label": lbl, "parts": parts} for lbl, parts in preset],
            "day_count": len(preset)}


def clear_workout_split(user_id: str) -> dict:
    """커스텀 분할을 제거해 프리셋으로 복귀시킨다."""
    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        if not user or not user.custom_split:
            return {"updated": False, "user_id": user_id,
                    "note": "저장된 커스텀 분할이 없어요(이미 프리셋)."}
        user.custom_split = None
        session.commit()
        return {"updated": True, "user_id": user_id, "note": "프리셋 분할로 되돌렸어요."}
    except Exception as e:
        session.rollback()
        return {"updated": False, "error": str(e)}
    finally:
        session.close()
