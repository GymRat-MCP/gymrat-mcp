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

def test_split_focus_english_alias():
    # 회귀: 호스트 LLM이 "lower body"(영문)로 보내도 한글 하체로 매핑
    label, targets = routine._decide_split(3, "lower body", history=[])
    assert label == "하체 집중"
    assert "하체" in targets

def test_split_focus_unknown_falls_back_not_empty():
    # 회귀: 미인식 focus는 빈 루틴 대신 일수 분할로 폴백
    label, targets = routine._decide_split(3, "asdf", history=[])
    assert targets  # 절대 비어있지 않음
    assert "집중" not in label  # focus 라벨이 아니라 분할 라벨

def test_normalize_focus_variants():
    assert routine._normalize_focus("CHEST") == "가슴"
    assert routine._normalize_focus("다리") == "하체"
    assert routine._normalize_focus("가슴") == "가슴"
    assert routine._normalize_focus(None) is None
    assert routine._normalize_focus("존재안함") is None


# ── _prescribe (역할별 sets/reps/휴식/강도, Phase A) ────────
def test_prescribe_compound_low_reps():
    # 컴파운드는 저~중반복 — 증량이라도 6회(고반복 아님)
    sets, reps, rest, rpe = routine._prescribe("compound", "증량", None)
    assert (sets, reps) == (4, 6)
    assert rest >= 120                     # 컴파운드는 긴 휴식

def test_prescribe_isolation_high_reps():
    # 고립은 중~고반복
    sets, reps, rest, rpe = routine._prescribe("isolation", "증량", None)
    assert reps >= 12
    assert rest <= 90                      # 고립은 짧은 휴식

def test_prescribe_cut_is_not_high_rep_compound():
    # 회귀: "감량이니까 고반복 15회" 오개념 제거 — 컴파운드는 감량에도 저~중반복
    _, reps, _, _ = routine._prescribe("compound", "감량", None)
    assert reps <= 8

def test_prescribe_beginner_lowers_sets():
    sets, _, _, _ = routine._prescribe("compound", "증량", "초보")
    assert sets == 3                       # 4 → 3

def test_prescribe_deload_lowers_sets_and_intensity():
    sets, _, _, rpe = routine._prescribe("compound", "증량", None, deload=True)
    assert sets == 3 and "회복" in rpe


# ── _progress (점진적 과부하 + 더블 프로그레션) ────────────
def test_progress_none_when_no_history():
    assert routine._progress("barbell bench press", {}, "가슴", 8) == (None, 8)

def test_progress_increment():
    # 직전 렙(reps 없음) → 목표 렙 달성으로 간주 → 무게↑
    idx = {"barbell bench press": {"weight": 80.0, "sets": 5, "reps": None}}
    assert routine._progress("barbell bench press", idx, "가슴", 8) == (82.5, 8)

def test_progress_leg_bigger_increment():
    idx = {"barbell full squat": {"weight": 100.0, "sets": 5, "reps": 8}}
    assert routine._progress("barbell full squat", idx, "하체", 8) == (105.0, 8)

def test_progress_double_progression_adds_rep():
    # 직전 렙(6)이 목표(8) 미달 → 무게 유지, 렙 +1
    idx = {"barbell bench press": {"weight": 80.0, "sets": 4, "reps": 6}}
    assert routine._progress("barbell bench press", idx, "가슴", 8) == (80.0, 7)

def test_progress_deload_drops_weight():
    # 디로드 주간 → 무게 -10%, 렙은 목표 리셋
    idx = {"barbell bench press": {"weight": 80.0, "sets": 5, "reps": 8}}
    assert routine._progress("barbell bench press", idx, "가슴", 8, deload=True) == (72.0, 8)


# ── _last_weight_index ─────────────────────────────────────
def test_last_weight_index_takes_most_recent():
    # history는 date desc → 먼저 본 항목이 최신, 이후 같은 종목은 무시
    history = [
        SimpleNamespace(parsed=[{"exercise": "벤치프레스", "weight": 82.5, "sets": 5, "reps": 5}]),
        SimpleNamespace(parsed=[{"exercise": "벤치프레스", "weight": 80.0, "sets": 5, "reps": 8}]),
    ]
    assert routine._last_weight_index(history) == {
        "벤치프레스": {"weight": 82.5, "sets": 5, "reps": 5}}


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
    assert first["role"] == "compound"                      # 벤치=컴파운드
    assert first["sets"] == 4 and first["reps"] == 6        # 증량 컴파운드
    assert first["target_load"] == 82.5                     # 과부하 반영
    assert first["rest_sec"] >= 120 and first["intensity"]  # Phase A 필드
    assert first["form_cues"] == ["a"]

def test_build_exercises_excludes_injury_movements(monkeypatch):
    # 회귀: 어깨 부상 시 오버헤드 프레스/업라이트로우는 제외돼야 함
    fake = {
        "어깨": [
            {"name": "barbell seated overhead press", "form_cues": [], "equipment": "바벨", "secondary": []},
            {"name": "barbell upright row", "form_cues": [], "equipment": "바벨", "secondary": []},
            {"name": "dumbbell lateral raise", "form_cues": [], "equipment": "덤벨", "secondary": []},
        ],
        "삼두": [
            {"name": "cable pushdown", "form_cues": [], "equipment": "케이블", "secondary": []},
        ],
    }
    monkeypatch.setattr(routine, "_query_exercises", lambda part, exp: fake.get(part, []))
    profile = SimpleNamespace(goal="증량", experience="중급", injuries="오른쪽 어깨 회전근개 부상")
    out = routine._build_exercises(["어깨", "삼두"], [], profile, None)
    names = [e["exercise"] for e in out]
    assert "barbell seated overhead press" not in names
    assert "barbell upright row" not in names
    assert "dumbbell lateral raise" in names   # 안전 종목은 유지
    assert names  # 빈 루틴 아님

def test_pick_complementary_prefers_new_pattern(monkeypatch):
    # 등: 첫 종목이 수평 당기기(로우)면 둘째는 수직 당기기(랫풀다운) 우선
    back = [
        {"name": "barbell bent over row", "form_cues": [], "equipment": "바벨", "secondary": ["이두"]},
        {"name": "cable seated row", "form_cues": [], "equipment": "케이블", "secondary": ["이두"]},
        {"name": "cable lat pulldown", "form_cues": [], "equipment": "케이블", "secondary": ["이두"]},
    ]
    monkeypatch.setattr(routine, "_query_exercises", lambda part, exp: back)
    profile = SimpleNamespace(goal="증량", experience="중급", injuries=None)
    out = routine._build_exercises(["등"], [], profile, None)
    keys = {routine._diversity_key(e["exercise"]) for e in out}
    # 로우 2종이 아니라 수평+수직 당기기 조합
    assert "수평당기기" in keys and "수직당기기" in keys


def test_technical_lift_deprioritized():
    # 올림픽/파워 리프트는 일반 루틴 선두에서 밀려야 함
    assert routine._is_technical_lift("barbell clean and press") == 1
    assert routine._is_technical_lift("dumbbell snatch") == 1
    assert routine._is_technical_lift("barbell full squat") == 0
    assert routine._is_technical_lift("barbell bench press") == 0


def test_injury_filters_keyword_match():
    parts, blocked = routine._injury_filters("어깨 회전근개")
    assert "어깨" in parts
    assert "overhead press" in blocked
    assert routine._injury_filters(None) == (set(), [])

def test_build_exercises_normalizes_experience(monkeypatch):
    # 회귀: "초보자"로 와도 초보 종목 필터가 먹어야 함
    seen = {}
    def fake_query(part, exp):
        seen["exp"] = exp
        return [{"name": "x", "form_cues": [], "equipment": "바벨", "secondary": []}]
    monkeypatch.setattr(routine, "_query_exercises", fake_query)
    profile = SimpleNamespace(goal="감량", experience="초보자", injuries=None)
    routine._build_exercises(["가슴"], [], profile, None)
    assert seen["exp"] == "초보"   # _query_exercises에 정규값 전달

def test_build_exercises_respects_session_cap(monkeypatch):
    many = [{"name": f"ex{i}", "form_cues": [], "equipment": "바벨", "secondary": []}
            for i in range(5)]
    monkeypatch.setattr(routine, "_query_exercises", lambda part, exp: many)
    profile = SimpleNamespace(goal=None, experience=None, injuries=None)
    # 3부위×부위당 2종 = 6 후보지만 48분 → cap = min(8, 48//12=4) = 4로 제한
    out = routine._build_exercises(["가슴", "삼두", "어깨"], [], profile, 48)
    assert len(out) == 4
