"""Phase 2 — 분석을 처방에 먹이기 (자동 디로드 + 더블 프로그레션 + 맨몸 볼륨, #14)."""
from types import SimpleNamespace
from datetime import date
from unittest.mock import patch, MagicMock

import tools.routine as routine
from tools.analysis import _trend_volume, _session_volume_with_bw


# ── 자동 디로드/과부하 분기 ────────────────────────────────
def test_is_deload_branches():
    assert routine._is_deload({"direction": "down", "flag": None}) is True
    assert routine._is_deload({"direction": "flat", "flag": "plateau"}) is True
    assert routine._is_deload({"direction": "up", "flag": None}) is False
    assert routine._is_deload({"direction": "flat", "flag": "insufficient_data"}) is False


def test_deload_lowers_sets_and_weight(monkeypatch):
    fake = {"가슴": [{"name": "barbell bench press", "form_cues": [],
                     "equipment": "바벨", "secondary": []}]}
    monkeypatch.setattr(routine, "_query_exercises", lambda part, exp, a=None: fake.get(part, []))
    profile = SimpleNamespace(goal="증량", experience="중급", injuries=None)
    history = [SimpleNamespace(parsed=[{"exercise": "벤치프레스", "weight": 80.0,
                                        "sets": 5, "reps": 8}])]
    trend = {"direction": "down", "flag": None}
    out = routine._build_exercises(["가슴"], history, profile, None, trend)
    ex = out[0]
    assert ex["sets"] == 3          # 증량 4 → 디로드 3
    assert ex["target_load"] == 72.0   # 80 * 0.9 (디로드)


def test_up_trend_keeps_overload(monkeypatch):
    fake = {"가슴": [{"name": "barbell bench press", "form_cues": [],
                     "equipment": "바벨", "secondary": []}]}
    monkeypatch.setattr(routine, "_query_exercises", lambda part, exp, a=None: fake.get(part, []))
    profile = SimpleNamespace(goal="증량", experience="중급", injuries=None)
    history = [SimpleNamespace(parsed=[{"exercise": "벤치프레스", "weight": 80.0,
                                        "sets": 5, "reps": 8}])]
    trend = {"direction": "up", "flag": None}
    out = routine._build_exercises(["가슴"], history, profile, None, trend)
    assert out[0]["sets"] == 4          # 디로드 아님
    assert out[0]["target_load"] == 82.5   # 목표 렙 달성 → 과부하


def test_deload_rationale_mentions_recovery():
    profile = SimpleNamespace(goal="증량", injuries=None)
    msg = routine._rationale(profile, "Push", [{}], {"direction": "down"}, deload=True)
    assert "회복" in msg


# ── 더블 프로그레션 (build 레벨) ──────────────────────────
def test_double_progression_adds_rep_when_below_target(monkeypatch):
    fake = {"가슴": [{"name": "barbell bench press", "form_cues": [],
                     "equipment": "바벨", "secondary": []}]}
    monkeypatch.setattr(routine, "_query_exercises", lambda part, exp, a=None: fake.get(part, []))
    profile = SimpleNamespace(goal="증량", experience="중급", injuries=None)
    # 직전 5렙 < 목표 6(증량 컴파운드) → 무게 유지, 렙 +1
    history = [SimpleNamespace(parsed=[{"exercise": "벤치프레스", "weight": 80.0,
                                        "sets": 4, "reps": 5}])]
    out = routine._build_exercises(["가슴"], history, profile, None,
                                   {"direction": "up"})
    assert out[0]["target_load"] == 80.0
    assert out[0]["reps"] == 6


# ── 맨몸 볼륨 프록시 ───────────────────────────────────────
def test_session_volume_with_bw_adds_bodyweight_proxy():
    parsed = [
        {"exercise": "벤치프레스", "weight": 80, "sets": 5, "reps": 5},   # 웨이트
        {"exercise": "풀업", "weight": None, "sets": 5, "reps": 8},        # 맨몸
    ]
    # 웨이트 2000 + 맨몸 70*0.5*5*8 = 1400 → 3400
    assert _session_volume_with_bw(parsed, 70.0) == 80*5*5 + 70*0.5*5*8


def test_session_volume_with_bw_skips_when_no_reps():
    # 플랭크(렙 None)는 프록시 제외 → 웨이트 볼륨만
    parsed = [{"exercise": "플랭크", "weight": None, "sets": 3, "reps": None}]
    assert _session_volume_with_bw(parsed, 70.0) == 0.0


@patch("tools.analysis._user_bodyweight", return_value=70.0)
@patch("tools.analysis.SessionLocal")
def test_bodyweight_only_sessions_not_false_down(mock_session_cls, _bw):
    # 맨몸 위주 세션들이 볼륨 0으로 빠지지 않고 시리즈에 포함 → insufficient 아님
    mock_logs = []
    for reps in [8, 9, 10, 11]:   # 오히려 상승
        log = MagicMock()
        log.parsed = [{"exercise": "풀업", "weight": None, "sets": 5, "reps": reps}]
        mock_logs.append(log)
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_logs
    mock_session_cls.return_value = mock_session

    result = _trend_volume("u", date(2026, 5, 23))
    assert result["flag"] != "insufficient_data"   # 시리즈로 잡힘
    assert result["direction"] == "up"             # 거짓 down 아님
