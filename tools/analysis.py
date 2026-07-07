"""추세 분석 — 체중 / 볼륨 / 인바디 / 식단의 시계열 패턴

이 시계열 누적·분석이 MCP의 차별점(일반 챗봇은 못 함).
⚠️ 가드레일: 정확 수치 단정 ❌ → 방향성·질적 summary 중심.
"""
from datetime import datetime, time, timedelta
from db.session import SessionLocal
from db.models import WeightLog, WorkoutLog, InbodyLog, MealLog
from tools.meal_intel import classify_meal_text, summarize_meal_classifications
from tools.persona import apply_persona, get_persona, persona_response_fields
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
    base_summary = "지원하지 않는 지표"
    summary = apply_persona(base_summary, persona)
    return {
        "direction": "flat",
        "summary": summary,
        "base_summary": base_summary,
        "flag": None,
        "persona": persona,
        **persona_response_fields(
            persona, base_summary, summary, fallback_field="summary"),
    }


def _with_persona(user_id: str, result: dict) -> dict:
    persona = get_persona(user_id)
    base_summary = result["summary"]
    summary = apply_persona(base_summary, persona)
    return {
        **result,
        "summary": summary,
        "base_summary": base_summary,
        "persona": persona,
        **persona_response_fields(
            persona, base_summary, summary, fallback_field="summary"),
    }


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


_BW_FACTOR = 0.5   # 맨몸 컴파운드 볼륨 프록시 계수(체중의 절반을 유효 부하로 근사)


def _user_bodyweight(user_id: str, default: float = 70.0) -> float:
    """최근 체중 기록을 맨몸 볼륨 프록시용으로 가져온다(없으면 기본값)."""
    session = SessionLocal()
    try:
        row = (session.query(WeightLog)
               .filter(WeightLog.user_id == user_id)
               .order_by(WeightLog.date.desc(), WeightLog.id.desc())
               .first())
    finally:
        session.close()
    w = getattr(row, "weight", None)
    return float(w) if isinstance(w, (int, float)) else default


def _session_volume_with_bw(parsed, bodyweight: float) -> float:
    """세션 볼륨 = 웨이트 볼륨 + 맨몸 컴파운드 프록시(reps×체중×계수).

    무게 None이라 session_volume이 빼버리는 풀업/딥스 등을 체중 프록시로 별도
    합산 → 맨몸 위주 세션이 볼륨 0으로 빠져 '거짓 down'을 만드는 문제를 완화(#14).
    """
    total = session_volume(parsed)
    for it in (parsed or []):
        if it.get("weight") is None:
            s, r = it.get("sets"), it.get("reps")
            if s and r:
                total += bodyweight * _BW_FACTOR * s * r
    return total


def _trend_volume(user_id: str, since) -> dict:
    # WorkoutLog.parsed에서 종목별 볼륨(weight*sets*reps) 합산 추세
    """ 운동 볼륨(weight×sets×reps) 추세를 분석한다.

        세션(날짜)별 총 볼륨을 만들고, 초반 절반 평균 vs 후반 절반 평균으로
        방향성을 본다. 맨몸 컴파운드는 체중 프록시로 별도 집계(#14).
        가드레일: 정확 수치 단정 X → 방향성·질적 요약.
    """
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

    # 세션별 총 볼륨(맨몸 프록시 포함) -> 0인 세션은 제외.
    # 체중은 맨몸 항목이 있을 때만 lazy 조회(웨이트-only면 DB 왕복 0).
    bodyweight = None
    volumes = []
    for log in logs:
        has_bw = any(it.get("weight") is None and it.get("sets") and it.get("reps")
                     for it in (log.parsed or []))
        if has_bw and bodyweight is None:
            bodyweight = _user_bodyweight(user_id)
        v = (_session_volume_with_bw(log.parsed, bodyweight)
             if has_bw else session_volume(log.parsed))
        if v > 0:
            volumes.append(v)

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
            "summary": "최근 식단 기록이 없어요. 오늘 먹은 걸 한 줄로 남기면 패턴을 잡아볼게요.",
            "flag": "insufficient_data",
        })

    classifications = [classify_meal_text(log.photo_analysis or "") for log in logs]
    scores = [classification["meal_score"] for classification in classifications]
    meal_pattern = summarize_meal_classifications(classifications)

    avg_score = _avg(scores)
    missing_majority = bool(meal_pattern["common_missing_axes"])
    if len(scores) >= 4:
        mid = len(scores) // 2
        direction = _direction(_avg(scores[:mid]), _avg(scores[mid:]), eps=0.25)
    else:
        direction = "up" if avg_score >= 2.3 else "flat" if avg_score >= 1.5 else "down"
    if direction == "flat" and missing_majority:
        direction = "down"

    axis_labels = {"protein": "단백질", "carb": "탄수화물", "vegetable": "채소"}
    missing_labels = [
        axis_labels.get(axis, axis)
        for axis in meal_pattern["common_missing_axes"]
    ]
    missing_text = "·".join(missing_labels) if missing_labels else "단백질·채소·탄수"
    summary = {
        "up": "최근 식단 기록은 균형이 좋아지는 흐름이에요. 단백질·채소·탄수 축을 계속 챙겨봐요.",
        "down": f"최근 식단은 {missing_text} 축이 자주 비어요. 다음 끼니에서 이 축부터 보완해봐요.",
        "flat": "식단은 대체로 비슷한 패턴이에요. 부족한 축 하나만 정해서 보완하면 좋아요.",
    }[direction]
    flag = "low_meal_logging" if len(logs) < 3 else "needs_balance" if direction == "down" else None
    return _with_persona(user_id, {
        "direction": direction,
        "summary": summary,
        "flag": flag,
        "meal_pattern": meal_pattern,
    })
