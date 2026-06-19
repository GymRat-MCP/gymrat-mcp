"""추세 분석 — 체중 / 볼륨 / 인바디 / 식단의 시계열 패턴

이 시계열 누적·분석이 MCP의 차별점(일반 챗봇은 못 함).
⚠️ 가드레일: 정확 수치 단정 ❌ → 방향성·질적 summary 중심.
"""
from datetime import datetime, timedelta
from db.session import SessionLocal
from db.models import WeightLog, WorkoutLog, InbodyLog, MealLog


def analyze_trend(user_id: str, metric: str = "weight",
                  period_days: int = 30) -> dict:
    """지정 지표의 최근 추세를 분석한다.

    metric: "weight" | "volume" | "inbody" | "meal"
    반환: {direction: up|down|flat, summary, flag}
    """
    since = datetime.now().date() - timedelta(days=period_days)

    if metric == "weight":
        return _trend_weight(user_id, since)
    elif metric == "volume":
        return _trend_volume(user_id, since)
    elif metric == "inbody":
        return _trend_inbody(user_id, since)
    elif metric == "meal":
        return _trend_meal(user_id, since)
    return {"direction": "flat", "summary": "지원하지 않는 지표", "flag": None}


def _direction(first: float, last: float, eps: float = 0.0) -> str:
    if last - first > eps:
        return "up"
    if first - last > eps:
        return "down"
    return "flat"


def _trend_weight(user_id: str, since) -> dict:
    # TODO: WeightLog 조회 → 첫/마지막 비교 → 선형 추세 + 질적 summary
    return {"direction": "flat", "summary": "체중 데이터 분석 (TODO)", "flag": None}


def _trend_volume(user_id: str, since) -> dict:
    # TODO: WorkoutLog.parsed에서 종목별 볼륨(weight*sets*reps) 합산 추세
    return {"direction": "flat", "summary": "볼륨 데이터 분석 (TODO)", "flag": None}


def _trend_inbody(user_id: str, since) -> dict:
    # TODO: 골격근량 / 체지방률 증감
    return {"direction": "flat", "summary": "인바디 데이터 분석 (TODO)", "flag": None}


def _trend_meal(user_id: str, since) -> dict:
    # TODO: 식단 로그 빈도/균형 패턴 (질적)
    return {"direction": "flat", "summary": "식단 데이터 분석 (TODO)", "flag": None}
