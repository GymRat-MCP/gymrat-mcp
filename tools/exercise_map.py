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
