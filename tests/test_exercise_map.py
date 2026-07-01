"""영↔한 종목 브리지 테스트 (Phase 1, 이슈 #13).

- 매핑 무결성: 키 == _CANON 28종, 값은 라이브러리에 실재.
- 라운드트립: 영문 대표명 → 정규 한글 → 원래 키.
- 골든: 28종 각각 "한글 로그 → 영문 처방"에서 점진적 과부하가 발화.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import tools.routine as routine
from tools.workout_parser import _CANON, parse_workout
from tools.exercise_map import KO_CANON_TO_LIB, lib_to_ko_canon

_LIB_NAMES = {
    x["name"] for x in json.loads(
        (Path(__file__).parent.parent / "data" / "exercises.json")
        .read_text(encoding="utf-8"))
}


# ── 매핑 무결성 ────────────────────────────────────────────
def test_map_keys_match_canon():
    # 브리지는 사람이 실제 로그하는 28종(_CANON 키)만 커버한다.
    assert set(KO_CANON_TO_LIB) == set(_CANON)


def test_map_values_exist_in_library():
    # ⚠️ 값이 라이브러리에 없으면 조용히 None → 과부하 미발화. 실재 검증.
    missing = {k: v for k, v in KO_CANON_TO_LIB.items() if v not in _LIB_NAMES}
    assert not missing, f"라이브러리에 없는 대표명: {missing}"


def test_map_values_unique():
    # 두 한글명이 같은 영문에 매핑되면 역방향이 하나로 뭉개진다.
    vals = list(KO_CANON_TO_LIB.values())
    assert len(vals) == len(set(vals))


# ── lib_to_ko_canon ────────────────────────────────────────
def test_round_trip_all():
    for ko, lib in KO_CANON_TO_LIB.items():
        assert lib_to_ko_canon(lib) == ko


def test_lib_to_ko_case_insensitive():
    assert lib_to_ko_canon("Barbell Bench Press") == "벤치프레스"
    assert lib_to_ko_canon("  barbell bench press  ") == "벤치프레스"


def test_lib_to_ko_unmapped_is_none():
    # 긴 꼬리(매핑 안 된 종목)는 None → 회귀 없음
    assert lib_to_ko_canon("barbell decline bench press") is None
    assert lib_to_ko_canon("") is None
    assert lib_to_ko_canon(None) is None


# ── 골든: 로그 → 처방 과부하 발화 (28종) ───────────────────
def test_golden_28_progression_fires():
    """각 정규 한글명으로 80kg 로그 → 영문 대표 처방에 82.5kg 발화."""
    failed = []
    for ko, lib in KO_CANON_TO_LIB.items():
        history = [SimpleNamespace(parsed=[{"exercise": ko, "weight": 80.0}])]
        idx = routine._last_weight_index(history)
        load = routine._progress(lib, idx, part="가슴")   # part 고정 → +2.5 검증
        if load != 82.5:
            failed.append((ko, lib, load))
    assert not failed, f"과부하 미발화: {failed}"


def test_dod_bench_80_to_82_5():
    """DoD: 사용자가 '벤치 80 5x5' 로그 → 처방 bench target_load == 82.5."""
    parsed, _ = parse_workout("벤치 80 5x5")
    assert parsed[0]["exercise"] == "벤치프레스" and parsed[0]["weight"] == 80.0
    history = [SimpleNamespace(parsed=parsed)]
    idx = routine._last_weight_index(history)
    assert routine._progress("barbell bench press", idx, "가슴") == 82.5


def test_leg_increment_via_bridge():
    # 하체는 +5kg 증량 — 스쿼트 로그 100 → 처방 105
    history = [SimpleNamespace(parsed=[{"exercise": "스쿼트", "weight": 100.0}])]
    idx = routine._last_weight_index(history)
    assert routine._progress("barbell full squat", idx, "하체") == 105.0


def test_unmapped_prescription_no_regression():
    # 매핑 안 된 처방 종목 + 관련 로그 없음 → None (기존 동작 유지)
    history = [SimpleNamespace(parsed=[{"exercise": "벤치프레스", "weight": 80.0}])]
    idx = routine._last_weight_index(history)
    assert routine._progress("barbell decline bench press", idx, "가슴") is None
