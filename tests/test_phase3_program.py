"""Phase 3 — 주기화 프로그램 (Program 주차 + 회복/빈도 + 패턴 균형, #15)."""
from types import SimpleNamespace
from datetime import date, timedelta

import tools.routine as routine
from tools.exercise_map import log_name_to_part, movement_pattern


# ── 패턴/부위 태깅 (exercise_map) ──────────────────────────
def test_movement_pattern_tags():
    assert movement_pattern("barbell bench press") == "밀기"
    assert movement_pattern("barbell bent over row") == "당기기"
    assert movement_pattern("dumbbell biceps curl") == "당기기"
    assert movement_pattern("barbell deadlift") == "힌지"
    assert movement_pattern("barbell full squat") == "스쿼트"
    assert movement_pattern("front plank with twist") == "코어"
    assert movement_pattern("cable pushdown") == "밀기"
    assert movement_pattern("something weird") == "기타"
    # 회귀: 카프레이즈는 '코어'가 아니라 '종아리'(예전 "raise" 오태깅)
    assert movement_pattern("barbell standing calf raise") == "종아리"
    assert movement_pattern("dumbbell seated calf raise") == "종아리"


def test_log_name_to_part():
    assert log_name_to_part("벤치") == "가슴"       # 별칭 정규화 경유
    assert log_name_to_part("스쿼트") == "하체"
    assert log_name_to_part("풀업") == "등"
    assert log_name_to_part("처음보는운동") is None


# ── Program 주차/디로드 (#15-1) ────────────────────────────
def test_program_state_week_derivation():
    prog = SimpleNamespace(started_at=date.today() - timedelta(days=14),
                           deload_every=4)
    week, is_deload = routine._program_state(prog)
    assert week == 3           # 14일 경과 → 3주차
    assert is_deload is False


def test_program_state_deload_on_nth_week():
    # 시작 후 21일 → 4주차 → deload_every=4의 배수 → 디로드
    prog = SimpleNamespace(started_at=date.today() - timedelta(days=21),
                           deload_every=4)
    week, is_deload = routine._program_state(prog)
    assert week == 4
    assert is_deload is True


# ── 회복/빈도 (#15-2) ──────────────────────────────────────
def test_recently_trained_parts_within_48h():
    history = [
        SimpleNamespace(date=date.today(),
                        parsed=[{"exercise": "벤치프레스", "sets": 4}]),
        SimpleNamespace(date=date.today() - timedelta(days=5),
                        parsed=[{"exercise": "스쿼트", "sets": 4}]),   # 오래됨
    ]
    parts = routine._recently_trained_parts(history)
    assert parts == {"가슴"}          # 어제/오늘 가슴만, 5일 전 하체는 제외


def test_weekly_balance_sums_sets_by_part():
    history = [
        SimpleNamespace(date=date.today(),
                        parsed=[{"exercise": "벤치프레스", "sets": 4},
                                {"exercise": "풀업", "sets": 3}]),
        SimpleNamespace(date=date.today() - timedelta(days=2),
                        parsed=[{"exercise": "인클라인벤치프레스", "sets": 3}]),
        SimpleNamespace(date=date.today() - timedelta(days=20),
                        parsed=[{"exercise": "스쿼트", "sets": 5}]),   # 주간 밖
    ]
    bal = routine._weekly_balance(history)
    assert bal == {"가슴": 7, "등": 3}


def test_recent_part_deprioritized_in_build(monkeypatch):
    # 어제 가슴 → 오늘 가슴 후순위(순서만, 제외 아님)
    fake = {
        "가슴": [{"name": "barbell bench press", "form_cues": [], "equipment": "바벨", "secondary": []}],
        "등": [{"name": "barbell bent over row", "form_cues": [], "equipment": "바벨", "secondary": []}],
    }
    monkeypatch.setattr(routine, "_query_exercises", lambda part, exp, a=None: fake.get(part, []))
    profile = SimpleNamespace(goal="증량", experience="중급", injuries=None)
    out = routine._build_exercises(["가슴", "등"], [], profile, None,
                                   trend={"direction": "up"},
                                   recent_parts={"가슴"})
    parts = [e["target"] for e in out]
    assert parts[0] == "등"          # 최근 자극 안 한 등이 앞으로
    assert "가슴" in parts           # 완전 제외는 아님


# ── 패턴 분포 (#15-3) ──────────────────────────────────────
def test_pattern_mix_counts():
    ex = [{"pattern": "밀기"}, {"pattern": "밀기"}, {"pattern": "당기기"}]
    assert routine._pattern_mix(ex) == {"밀기": 2, "당기기": 1}


# ── rationale 주간 볼륨 부족 언급 (#15-2) ──────────────────
def test_rationale_flags_low_weekly_volume():
    profile = SimpleNamespace(goal="증량", injuries=None)
    msg = routine._rationale(profile, "Push", [{}], {"direction": "up"},
                             deload=False, balance={"등": 4})   # 10 미만
    assert "등" in msg and "볼륨" in msg
