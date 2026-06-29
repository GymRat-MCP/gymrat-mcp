"""추세 분석 — 체중 / 볼륨 / 인바디 / 식단의 시계열 패턴

이 시계열 누적·분석이 MCP의 차별점(일반 챗봇은 못 함).
⚠️ 가드레일: 정확 수치 단정 ❌ → 방향성·질적 summary 중심.
"""
from datetime import datetime, time, timedelta
from db.session import SessionLocal
from db.models import WeightLog, WorkoutLog, InbodyLog, MealLog
from tools.persona import apply_persona, get_persona
from tools.workout_parser import session_volume

_session_volume = session_volume


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
    persona = get_persona(user_id)
    return {
        "direction": "flat",
        "summary": apply_persona("지원하지 않는 지표", persona),
        "flag": None,
        "persona": persona,
    }


def _with_persona(user_id: str, result: dict) -> dict:
    persona = get_persona(user_id)
    return {**result, "summary": apply_persona(result["summary"], persona), "persona": persona}


def _direction(first: float, last: float, eps: float = 0.0) -> str:
    if last - first > eps:
        return "up"
    if first - last > eps:
        return "down"
    return "flat"


def _start_of_day(day) -> datetime:
    return datetime.combine(day, time.min)


def _avg(values: list[float]) -> float:
    return sum(values) / len(values)


def _has_any(text: str, words: list[str]) -> bool:
    lowered = (text or "").lower()
    return any(word in lowered for word in words)


def _trend_weight(user_id: str, since) -> dict:
    session = SessionLocal()
    try:
        logs = (
            session.query(WeightLog)
            .filter(WeightLog.user_id == user_id, WeightLog.date >= since)
            .order_by(WeightLog.date.asc(), WeightLog.id.asc())
            .all()
        )
    finally:
        session.close()

    if len(logs) < 2:
        return _with_persona(user_id, {
            "direction": "flat",
            "summary": "체중 추세를 보려면 기록이 조금 더 필요해요.",
            "flag": "insufficient_data",
        })

    first = logs[0].weight
    last = logs[-1].weight
    direction = _direction(first, last, eps=0.3)
    summary = {
        "up": "최근 체중은 완만히 오르는 흐름이에요. 증량 중이라면 좋은 신호예요.",
        "down": "최근 체중은 내려가는 흐름이에요. 감량 중이라면 방향은 잘 잡혀 있어요.",
        "flat": "체중은 큰 변화 없이 유지 중이에요. 목표에 따라 식사량이나 활동량을 조금 조정해봐요.",
    }[direction]
    return _with_persona(user_id, {"direction": direction, "summary": summary, "flag": None})


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
        return _with_persona(user_id, {"direction": "flat",
                "summary": "볼륨 추세를 보려면 운동 기록이 좀 더 필요해요.", "flag": "insufficient_data"})
    
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


    return _with_persona(user_id, {"direction": direction,
            "summary": summary,
            "flag": "plateau" if direction == "flat" else None})


def _trend_inbody(user_id: str, since) -> dict:
    session = SessionLocal()
    try:
        logs = (
            session.query(InbodyLog)
            .filter(InbodyLog.user_id == user_id, InbodyLog.measured_date >= since)
            .order_by(InbodyLog.measured_date.asc(), InbodyLog.id.asc())
            .all()
        )
    finally:
        session.close()

    comparable = [
        log for log in logs
        if log.skeletal_muscle is not None or log.body_fat_pct is not None
    ]
    if len(comparable) < 2:
        return _with_persona(user_id, {
            "direction": "flat",
            "summary": "인바디 추세를 보려면 비교할 기록이 더 필요해요.",
            "flag": "insufficient_data",
        })

    first = comparable[0]
    last = comparable[-1]
    muscle_delta = (
        last.skeletal_muscle - first.skeletal_muscle
        if last.skeletal_muscle is not None and first.skeletal_muscle is not None
        else None
    )
    fat_delta = (
        last.body_fat_pct - first.body_fat_pct
        if last.body_fat_pct is not None and first.body_fat_pct is not None
        else None
    )

    positive = (
        (muscle_delta is not None and muscle_delta > 0.2)
        or (fat_delta is not None and fat_delta < -0.5)
    )
    negative = (
        (muscle_delta is not None and muscle_delta < -0.2)
        or (fat_delta is not None and fat_delta > 0.5)
    )
    direction = "up" if positive and not negative else "down" if negative and not positive else "flat"

    parts = []
    if muscle_delta is not None:
        parts.append(f"골격근량 {muscle_delta:+.1f}kg")
    if fat_delta is not None:
        parts.append(f"체지방률 {fat_delta:+.1f}%p")
    change_text = ", ".join(parts) if parts else "비교 가능한 주요 수치 변화가 제한적"

    summary = {
        "up": f"인바디 흐름은 좋아요. {change_text} 변화가 보여요.",
        "down": f"인바디 흐름은 점검이 필요해요. {change_text} 변화가 있어요.",
        "flat": f"인바디는 대체로 유지 중이에요. {change_text} 수준입니다.",
    }[direction]
    return _with_persona(user_id, {
        "direction": direction,
        "summary": summary,
        "flag": "check_recovery" if direction == "down" else None,
    })


def _trend_meal(user_id: str, since) -> dict:
    protein_words = ["단백질", "닭", "계란", "달걀", "고기", "생선", "두부", "콩", "요거트"]
    veggie_words = ["채소", "야채", "샐러드", "나물", "브로콜리", "양배추", "상추", "김치"]
    carb_words = ["밥", "현미", "고구마", "감자", "빵", "면", "파스타", "오트", "떡"]

    session = SessionLocal()
    try:
        logs = (
            session.query(MealLog)
            .filter(MealLog.user_id == user_id, MealLog.logged_at >= _start_of_day(since))
            .order_by(MealLog.logged_at.asc(), MealLog.id.asc())
            .all()
        )
    finally:
        session.close()

    if not logs:
        return _with_persona(user_id, {
            "direction": "flat",
            "summary": "최근 식단 기록이 없어요. 사진 한 장부터 남기면 패턴을 잡아볼게요.",
            "flag": "insufficient_data",
        })

    scores = []
    category_hits = {"protein": 0, "veggie": 0, "carb": 0}
    for log in logs:
        text = log.photo_analysis or ""
        has_protein = _has_any(text, protein_words)
        has_veggie = _has_any(text, veggie_words)
        has_carb = _has_any(text, carb_words)
        score = 0
        score += 1 if has_protein else 0
        score += 1 if has_veggie else 0
        score += 1 if has_carb else 0
        category_hits["protein"] += 1 if has_protein else 0
        category_hits["veggie"] += 1 if has_veggie else 0
        category_hits["carb"] += 1 if has_carb else 0
        scores.append(score)

    avg_score = _avg(scores)
    missing_majority = min(category_hits.values()) < len(scores) / 2
    if len(scores) >= 4:
        mid = len(scores) // 2
        direction = _direction(_avg(scores[:mid]), _avg(scores[mid:]), eps=0.25)
    else:
        direction = "up" if avg_score >= 2.3 else "flat" if avg_score >= 1.5 else "down"
    if direction == "flat" and missing_majority:
        direction = "down"

    summary = {
        "up": "최근 식단 기록은 균형이 좋아지는 흐름이에요. 단백질·채소·탄수 축을 계속 챙겨봐요.",
        "down": "최근 식단은 균형 축이 자주 비어요. 다음 끼니에서 단백질이나 채소를 먼저 보완해봐요.",
        "flat": "식단은 대체로 비슷한 패턴이에요. 부족한 축 하나만 정해서 보완하면 좋아요.",
    }[direction]
    flag = "low_meal_logging" if len(logs) < 3 else "needs_balance" if direction == "down" else None
    return _with_persona(user_id, {"direction": direction, "summary": summary, "flag": flag})
