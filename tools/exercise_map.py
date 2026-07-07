"""영↔한 종목 브리지 (Phase 1, 이슈 #13).

끊김 A 제거: 라이브러리 종목명은 영문(`barbell bench press`), 사용자 로그는
한글 canonical(`벤치프레스`)이라 매칭이 안 돼 `routine._progress()`가 거의 항상
None → 점진적 과부하가 사실상 발화 안 함(기록↔처방 단절).

사람이 실제 로그하는 28종(`workout_parser._CANON` 키)만 라이브러리 대표 영문명
1개로 손수 매핑한다. 종목당 후보가 여럿(bench는 32건)이라 바벨/컴파운드를 우선해
대표 1개를 고정했다. 긴 꼬리(1,324개)는 무시 — 매핑 안 된 종목은 기존대로 None(회귀 없음).

⚠️ 값(영문명)은 전부 seed된 `ExerciseLibrary.name`에 실재해야 한다
(`tests/test_exercise_map.py`에서 커버리지 검증).
"""
from tools.workout_parser import normalize_exercise

# 정규 한글명(_CANON 키) → 라이브러리 영문 대표 종목명 1개.
KO_CANON_TO_LIB = {
    # ── 가슴 ──
    "벤치프레스": "barbell bench press",
    "인클라인벤치프레스": "barbell incline bench press",
    "덤벨벤치프레스": "dumbbell bench press",
    "딥스": "chest dip",
    "체스트프레스": "lever chest press",
    "케이블플라이": "cable middle fly",
    # ── 등 ──
    "데드리프트": "barbell deadlift",
    "바벨로우": "barbell bent over row",
    "풀업": "pull-up",
    "랫풀다운": "cable lat pulldown full range of motion",
    "시티드로우": "cable seated row",
    # ── 어깨 ──
    "오버헤드프레스": "barbell seated overhead press",
    "사이드레터럴레이즈": "dumbbell lateral raise",
    "페이스풀": "cable rear delt row (with rope)",
    # ── 하체 ──
    "스쿼트": "barbell full squat",
    "레그프레스": "smith leg press",
    "레그컬": "lever lying leg curl",
    "레그익스텐션": "lever leg extension",
    "런지": "barbell lunge",
    "힙쓰러스트": "barbell glute bridge",
    "카프레이즈": "barbell standing calf raise",
    # ── 팔 ──
    "덤벨컬": "dumbbell biceps curl",
    "바벨컬": "barbell curl",
    "해머컬": "dumbbell hammer curl",
    "트라이셉스익스텐션": "barbell lying triceps extension",
    "케이블푸시다운": "cable pushdown",
    # ── 코어 ──
    "플랭크": "front plank with twist",
    "크런치": "crunch floor",
}

# 역방향: 라이브러리 영문 대표명 → 정규 한글명.
# (라이브러리 name은 seed 시 소문자라 조회 키도 소문자로 정규화)
LIB_TO_KO_CANON = {v.lower(): k for k, v in KO_CANON_TO_LIB.items()}


def lib_to_ko_canon(name: str | None) -> str | None:
    """라이브러리 영문 종목명을 사용자 로그의 정규 한글명으로 변환한다.

    매핑된 28종 대표명만 변환하고, 그 외(긴 꼬리)는 None을 반환한다.
    None이면 호출부가 점진적 과부하를 발화하지 않는다(회귀 없음).
    """
    if not name:
        return None
    return LIB_TO_KO_CANON.get(name.strip().lower())


# ── 정규 한글명 → 자극 부위(회복/빈도 추적용, Phase 3 #15-2) ──
# 로그(한글)에서 최근 자극 부위를 뽑아 48h 중복 타격 회피·주간 볼륨 집계에 쓴다.
KO_CANON_TO_PART = {
    "벤치프레스": "가슴", "인클라인벤치프레스": "가슴", "덤벨벤치프레스": "가슴",
    "딥스": "가슴", "체스트프레스": "가슴", "케이블플라이": "가슴",
    "데드리프트": "등", "바벨로우": "등", "풀업": "등",
    "랫풀다운": "등", "시티드로우": "등",
    "오버헤드프레스": "어깨", "사이드레터럴레이즈": "어깨", "페이스풀": "어깨",
    "스쿼트": "하체", "레그프레스": "하체", "레그컬": "하체",
    "레그익스텐션": "하체", "런지": "하체", "힙쓰러스트": "하체",
    "카프레이즈": "종아리",
    "덤벨컬": "이두", "바벨컬": "이두", "해머컬": "이두",
    "트라이셉스익스텐션": "삼두", "케이블푸시다운": "삼두",
    "플랭크": "코어", "크런치": "코어",
}


def log_name_to_part(logged_name: str | None) -> str | None:
    """사용자 로그 종목명(별칭·영문 포함)을 자극 부위로 변환. 미지정이면 None."""
    if not logged_name:
        return None
    return KO_CANON_TO_PART.get(normalize_exercise(logged_name))


# ── 움직임 패턴 태그 (하루 안 패턴 분산, Phase 3 #15-3) ──
# 라이브러리 영문 종목명 부분일치로 밀기/당기기/힌지/스쿼트/코어를 부여한다.
# "근육 수프"(예: 가슴 6종) 방지를 위해 처방 시 패턴 다양성을 확인하는 용도.
_PATTERN_RULES = [
    ("스쿼트", ("squat", "leg press", "lunge", "leg extension", "step-up", "step up")),
    ("힌지",   ("deadlift", "hip thrust", "glute bridge", "good morning",
               "romanian", "leg curl", "back extension", "hyperextension")),
    ("당기기", ("row", "pull-up", "pullup", "pull up", "pulldown", "pull-down",
               "curl", "face pull", "rear delt", "shrug", "chin-up", "chinup")),
    ("밀기",   ("bench press", "chest press", "overhead press", "shoulder press",
               "military press", "push-up", "push up", "pushdown", "dip",
               "fly", "flye", "crossover", "extension", "lateral raise",
               "front raise", "press")),
    ("코어",   ("plank", "crunch", "sit-up", "situp", "twist", "raise",
               "rollout", "rollerout", "hollow", "woodchop")),
]


def movement_pattern(name: str | None) -> str:
    """라이브러리 영문 종목명의 움직임 패턴을 반환한다(없으면 '기타')."""
    if not name:
        return "기타"
    low = name.lower()
    for pattern, keys in _PATTERN_RULES:
        if any(k in low for k in keys):
            return pattern
    return "기타"


# ── 종목 역할: 컴파운드 vs 고립 (Phase A — 역할별 처방) ──
# 다관절(컴파운드)은 저~중반복·긴 휴식, 단관절(고립)은 중~고반복·짧은 휴식으로
# 처방을 분기한다. "스쿼트도 4×8, 레터럴 레이즈도 4×8"처럼 전 종목 동일 처방을 막음.
# 단관절 신호가 우선(leg extension·rear delt row처럼 'row/press'가 섞여도 고립).
_ISOLATION_KEYS = (
    "curl", "extension", "raise", "fly", "flye", "pushdown", "kickback",
    "pullover", "shrug", "crossover", "lateral", "rear delt", "pec deck",
    "leg curl", "leg extension", "calf", "concentration",
)
_COMPOUND_KEYS = (
    "squat", "deadlift", "bench press", "press", "row", "pull-up", "pullup",
    "pull up", "chin-up", "chinup", "chin up", "pulldown", "pull-down",
    "lunge", "dip", "thruster", "clean", "snatch", "hip thrust",
    "glute bridge", "leg press", "good morning", "step-up", "step up",
    "push-up", "push up",
)


def exercise_role(name: str | None, secondary: list | None = None) -> str:
    """종목을 'compound'|'isolation'으로 분류한다.

    단관절 키워드가 있으면 고립(우선), 다관절 키워드면 컴파운드,
    둘 다 없으면 보조근 수(secondary≥2 → 컴파운드)로 폴백.
    """
    low = (name or "").lower()
    if any(k in low for k in _ISOLATION_KEYS):
        return "isolation"
    if any(k in low for k in _COMPOUND_KEYS):
        return "compound"
    return "compound" if len(secondary or []) >= 2 else "isolation"
