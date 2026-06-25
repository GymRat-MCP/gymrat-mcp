"""workout_parser 단위 테스트 — 파싱/정규화/누락확인 (DB 불필요, 순수함수)"""
from tools.workout_parser import (
    parse_workout, normalize_exercise, needs_confirmation, session_volume,
)


# ── normalize_exercise ─────────────────────────────────────
def test_normalize_alias():
    assert normalize_exercise("벤치") == "벤치프레스"
    assert normalize_exercise("bench") == "벤치프레스"
    assert normalize_exercise(" 사레레 ") == "사이드레터럴레이즈"

def test_normalize_unknown_passthrough():
    assert normalize_exercise("처음보는운동") == "처음보는운동"


# ── parse_workout: NxN 형식 ────────────────────────────────
def test_parse_nxn():
    parsed, needs = parse_workout("벤치 70 5x5, 인클 60 3x10")
    assert parsed[0] == {"exercise": "벤치프레스", "weight": 70.0, "sets": 5, "reps": 5}
    assert parsed[1]["exercise"] == "인클라인벤치프레스"
    assert needs == []


# ── parse_workout: 한글/단위 토큰 ──────────────────────────
def test_parse_korean_tokens():
    parsed, _ = parse_workout("스쿼트 100kg 3세트 10회")
    assert parsed[0] == {"exercise": "스쿼트", "weight": 100.0, "sets": 3, "reps": 10}

def test_parse_partial_korean():
    parsed, needs = parse_workout("데드 60 8회")
    assert parsed[0]["weight"] == 60.0
    assert parsed[0]["reps"] == 8
    assert parsed[0]["sets"] is None
    assert needs == ["데드리프트: 세트 누락"]


# ── parse_workout: 맨몸(무게 누락) ─────────────────────────
def test_parse_bodyweight_needs():
    parsed, needs = parse_workout("풀업 3x10")
    assert parsed[0]["weight"] is None
    assert needs == ["풀업: 무게 누락"]


# ── needs_confirmation 헬퍼 ────────────────────────────────
def test_needs_confirmation_combined():
    parsed = [{"exercise": "딥스", "weight": None, "sets": 3, "reps": None}]
    assert needs_confirmation(parsed) == ["딥스: 무게·반복 누락"]

def test_needs_confirmation_none_when_complete():
    parsed = [{"exercise": "벤치프레스", "weight": 70, "sets": 5, "reps": 5}]
    assert needs_confirmation(parsed) == []


# ── session_volume ─────────────────────────────────────────
def test_session_volume_skips_incomplete():
    parsed = [
        {"weight": 100, "sets": 3, "reps": 10},   # 3000
        {"weight": None, "sets": 3, "reps": 10},  # 맨몸 → 제외
    ]
    assert session_volume(parsed) == 3000
