"""routine 엔진 단위 테스트 — 순수 헬퍼는 DB 불필요, 종목조회는 monkeypatch"""
from types import SimpleNamespace
import tools.routine as routine


# ── _decide_split ──────────────────────────────────────────
def test_split_focus():
    label, targets = routine._decide_split(3, "가슴", history=[])
    assert label == "가슴 집중"
    assert targets[0] == "가슴"

def test_split_by_days_no_history():
    label, targets = routine._decide_split(3, None, history=[])
    # 기록 0개 → 분할 첫째 날(Push)
    assert "Push" in label
    assert "가슴" in targets

def test_split_rotation_by_history():
    # 3일 분할(길이 3)에서 기록 1개 → 둘째 날(Pull)
    label, targets = routine._decide_split(3, None, history=[object()])
    assert "Pull" in label

def test_split_days_clamped():
    # 10일 요청 → 6일 분할로 클램프(에러 없이)
    label, targets = routine._decide_split(10, None, history=[])
    assert targets  # 비어있지 않음


# ── _sets_reps ─────────────────────────────────────────────
def test_sets_reps_by_goal():
    assert routine._sets_reps("증량", None) == (4, 8)
    assert routine._sets_reps("감량", None) == (3, 15)
    assert routine._sets_reps("유지", None) == (3, 12)
    assert routine._sets_reps(None, None) == (3, 12)

def test_sets_reps_beginner_lowers_sets():
    assert routine._sets_reps("증량", "초보") == (3, 8)


# ── _progress (점진적 과부하) ──────────────────────────────
def test_progress_none_when_no_history():
    assert routine._progress("barbell bench press", {}, "가슴") is None

def test_progress_increment():
    idx = {"barbell bench press": 80.0}
    assert routine._progress("barbell bench press", idx, "가슴") == 82.5

def test_progress_leg_bigger_increment():
    idx = {"barbell full squat": 100.0}
    assert routine._progress("barbell full squat", idx, "하체") == 105.0


# ── _last_weight_index ─────────────────────────────────────
def test_last_weight_index_takes_most_recent():
    # history는 date desc → 먼저 본 항목이 최신, 이후 같은 종목은 무시
    history = [
        SimpleNamespace(parsed=[{"exercise": "벤치프레스", "weight": 82.5}]),
        SimpleNamespace(parsed=[{"exercise": "벤치프레스", "weight": 80.0}]),
    ]
    assert routine._last_weight_index(history) == {"벤치프레스": 82.5}


# ── _build_exercises (종목조회 monkeypatch) ────────────────
def test_build_exercises_structure(monkeypatch):
    fake = {
        "가슴": [
            {"name": "barbell bench press", "form_cues": ["a"], "equipment": "바벨", "secondary": ["삼두"]},
            {"name": "dumbbell fly", "form_cues": ["b"], "equipment": "덤벨", "secondary": []},
        ],
        "삼두": [
            {"name": "barbell close-grip bench press", "form_cues": ["c"], "equipment": "바벨", "secondary": []},
        ],
    }
    monkeypatch.setattr(routine, "_query_exercises",
                        lambda part, exp: fake.get(part, []))
    profile = SimpleNamespace(goal="증량", experience="중급", injuries=None)
    history = [SimpleNamespace(parsed=[{"exercise": "barbell bench press", "weight": 80.0}])]

    out = routine._build_exercises(["가슴", "삼두"], history, profile, None)
    # 부위가 2개(≤3)이므로 부위당 2종 → 가슴 2 + 삼두 1 = 3
    assert len(out) == 3
    first = out[0]
    assert first["exercise"] == "barbell bench press"
    assert first["sets"] == 4 and first["reps"] == 8       # 증량
    assert first["target_load"] == 82.5                     # 과부하 반영
    assert first["form_cues"] == ["a"]

def test_build_exercises_respects_session_cap(monkeypatch):
    many = [{"name": f"ex{i}", "form_cues": [], "equipment": "바벨", "secondary": []}
            for i in range(5)]
    monkeypatch.setattr(routine, "_query_exercises", lambda part, exp: many)
    profile = SimpleNamespace(goal=None, experience=None, injuries=None)
    # 3부위×부위당 2종 = 6 후보지만 48분 → cap = min(8, 48//12=4) = 4로 제한
    out = routine._build_exercises(["가슴", "삼두", "어깨"], [], profile, 48)
    assert len(out) == 4
