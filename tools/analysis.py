"""추세 분석 — 체중 / 볼륨 / 인바디 / 식단의 시계열 패턴

이 시계열 누적·분석이 MCP의 차별점(일반 챗봇은 못 함).
⚠️ 가드레일: 정확 수치 단정 ❌ → 방향성·질적 summary 중심.
"""
from datetime import datetime, timedelta
from db.session import SessionLocal
from db.models import WeightLog, WorkoutLog, InbodyLog, MealLog
from tools.workout_parser import session_volume


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
    # WorkoutLog.parsed에서 종목별 볼륨(weight*sets*reps) 합산 추세
    """ 운동 볼륨(weight×sets×reps) 추세를 분석한다.

        세션(날짜)별 총 볼륨을 만들고, 초반 절반 평균 vs 후반 절반 평균으로
        방향성을 본다. 
        가드레일: 정확 수치 단정 X → 방향성·질적 요약.
    """

    # TODO: 맨몸 운동은 volume이 없는데 v1은 이대로 진행 추후 볼륨 산정 기준을 바꿀 수도 있음

    session = SessionLocal()
    try:
        logs = (
            session.query(WorkoutLog)
            .filter(WorkoutLog.user_id == user_id,
                    WorkoutLog.date >= since)
            .order_by(WorkoutLog.date.asc())
            .all()
        )
    finally:
        session.close()

    # 세션별 총 볼륨 -> 0인 세션은 제외
    volumes = [v for log in logs if (v := session_volume(log.parsed)) > 0]

    if len(volumes) < 2:
        return {"direction": "flat", 
                "summary": "볼륨 추세를 보려면 운동 기록이 좀 더 필요해요.", "flag": "insufficient_data"}
    
    # 초반 절반 vs 후반 절반 평균 비교
    mid = len(volumes) // 2
    first_half_avg = sum(volumes[:mid]) / mid
    second_half_avg = sum(volumes[mid:]) / (len(volumes) - mid)

    
    eps = first_half_avg * 0.05          # 5% 미만 변화는 flat 취급
    direction = _direction(first_half_avg, second_half_avg, eps)  

    summary = {
        "up":   "최근 볼륨이 오르는 추세예요. 점진적 과부하가 잘 되고 있네요.",
        "down": "최근 볼륨이 줄어드는 흐름이에요. 피로·컨디션을 점검해봐요.",
        "flat": "볼륨이 대체로 유지 중이에요. 무게나 세트로 자극을 살짝 올려볼 때.",
    }[direction]


    return {"direction": direction,
            "summary": summary,
            "flag": "plateau" if direction == "flat" else None}


def _trend_inbody(user_id: str, since) -> dict:
    # TODO: 골격근량 / 체지방률 증감
    return {"direction": "flat", "summary": "인바디 데이터 분석 (TODO)", "flag": None}


def _trend_meal(user_id: str, since) -> dict:
    # TODO: 식단 로그 빈도/균형 패턴 (질적)
    return {"direction": "flat", "summary": "식단 데이터 분석 (TODO)", "flag": None}
