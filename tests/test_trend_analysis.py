import pytest
from datetime import date
from unittest.mock import patch, MagicMock
from tools.analysis import _trend_volume, _session_volume


# _session_volume의 단위 테스트 (db mocking)
def test_session_volume_normal():
  parsed = [
    {"weight": 100, "sets": 3, "reps": 10},
    {"weight": 80, "sets": 4, "reps": 8},
  ]
  assert _session_volume(parsed) == 100*3*10 + 80*4*8

def test_session_volume_missing_field():
  parsed = [
    {"weight": 100, "sets": 3},  # reps 누락
  ]
  assert _session_volume(parsed) == 0.0

def test_session_volume_empty():
  assert _session_volume([]) == 0.0
  assert _session_volume(None) == 0.0


# _trend_volume DB mocking test
@patch("tools.analysis.SessionLocal")
def test_trend_volume_up(mock_session_cls):
  # mock db going up
  mock_logs = []
  volumes = [1000, 1100, 1200, 1300, 1400, 1500]
  for v in volumes:
    log = MagicMock()
    log.parsed = [{"weight": v/30, "sets": 3, "reps": 10}]
    mock_logs.append(log)

  mock_session = MagicMock()
  mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_logs
  mock_session_cls.return_value = mock_session

  result = _trend_volume("user_1", date(2026, 5, 23))
  assert result["direction"] == "up"

@patch("tools.analysis.SessionLocal")
def test_trend_volume_insufficient(mock_session_cls):
  # 데이터 1개 → insufficient_data
  mock_session = MagicMock()
  mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
  mock_session_cls.return_value = mock_session

  result = _trend_volume("user_1", date(2026, 5, 23))
  assert result["flag"] == "insufficient_data"