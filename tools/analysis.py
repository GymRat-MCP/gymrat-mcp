"""추세 분석 — 체중 / 볼륨 / 인바디 / 식단의 시계열 패턴

이 시계열 누적·분석이 MCP의 차별점(일반 챗봇은 못 함).
⚠️ 가드레일: 정확 수치 단정 ❌ → 방향성·질적 summary 중심.
"""
from collections import defaultdict
from datetime import datetime, date as _date, time, timedelta
from db.session import SessionLocal
from db.models import WeightLog, WorkoutLog, InbodyLog, MealLog, ExerciseSet
from tools.meal_intel import classify_meal_text, summarize_meal_classifications
from tools.persona import apply_persona, get_persona, persona_response_fields
from tools.workout_parser import session_volume, normalize_exercise
from tools.exercise_map import log_name_to_part

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


# ─────────────────────────────────────────────────────────────
# P1 — e1RM & 종목별 히스토리 (ExerciseSet 기반)
# "내 벤치가 는다"를 숫자로. ②(진전 가시화)의 본체.
# ─────────────────────────────────────────────────────────────

_E1RM_HIGH_REP = 12   # reps>이면 e1RM 신뢰도 낮음(가드레일 표시)


def estimate_1rm(weight, reps) -> float | None:
    """Epley 추정 1RM: weight*(1+reps/30). reps=1이면 그대로.

    맨몸(weight=None)이거나 reps가 없/무효(<1)면 None(추정 불가).
    reps>12는 신뢰도가 낮아지지만 값은 계산한다(호출부에서 플래그).
    """
    if weight is None or reps is None:
        return None
    try:
        w = float(weight)
        r = int(reps)
    except (TypeError, ValueError):
        return None
    if r < 1:
        return None
    if r == 1:
        return w
    return w * (1 + r / 30)


def _exercise_series(user_id: str, exercise: str, since) -> list[dict]:
    """종목 단일 시계열을 ExerciseSet에서 집계한다.

    워밍업 세트는 통계에서 제외하고, 날짜별로
      top_weight(최고 중량), best_e1rm(최고 추정 1RM), volume(Σ weight*reps)
    를 만든다. exercise 는 normalize_exercise 로 정규화해 조회한다.
    반환: [{date(iso), top_weight, best_e1rm, volume}] (날짜 오름차순)
    """
    canon = normalize_exercise(exercise)
    session = SessionLocal()
    try:
        rows = (
            session.query(ExerciseSet)
            .filter(ExerciseSet.user_id == user_id,
                    ExerciseSet.exercise == canon,
                    ExerciseSet.date >= since,
                    ExerciseSet.is_warmup.isnot(True))   # 워밍업 제외(None=본세트 취급)
            .order_by(ExerciseSet.date.asc(), ExerciseSet.id.asc())
            .all()
        )
    finally:
        session.close()

    # 날짜별 집계(입력 순서 유지 → 날짜 오름차순 보존)
    by_date: dict = {}
    for r in rows:
        day = r.date
        agg = by_date.setdefault(day, {"top_weight": None, "best_e1rm": None,
                                       "volume": 0.0, "high_rep": False})
        if r.weight is not None:
            if agg["top_weight"] is None or r.weight > agg["top_weight"]:
                agg["top_weight"] = float(r.weight)
            if r.reps:
                agg["volume"] += float(r.weight) * int(r.reps)
        e = estimate_1rm(r.weight, r.reps)
        if e is not None:
            if agg["best_e1rm"] is None or e > agg["best_e1rm"]:
                agg["best_e1rm"] = e
            if r.reps and int(r.reps) > _E1RM_HIGH_REP:
                agg["high_rep"] = True

    points = []
    for day, agg in by_date.items():
        points.append({
            "date": day.isoformat(),
            "top_weight": agg["top_weight"],
            "best_e1rm": round(agg["best_e1rm"], 1) if agg["best_e1rm"] is not None else None,
            "volume": round(agg["volume"], 1),
        })
    return points


def get_exercise_history(user_id: str, exercise: str,
                         period_days: int = 90) -> dict:
    """종목별 단일 시계열 + e1RM 추세를 반환한다(P1).

    반환: {exercise(정규화명), points[], e1rm_trend:{direction, pct_change}, note, flag}
    가드레일: note 는 방향성·질적 문장. pct_change 는 데이터 필드(참고용).
    응답에 assistant_message 가 있으면 사용자에게 이 문장을 우선 전달한다.
    """
    canon = normalize_exercise(exercise)
    since = datetime.now().date() - timedelta(days=period_days)
    points = _exercise_series(user_id, exercise, since)

    # e1RM 추세: e1rm 있는 포인트만으로 첫 vs 마지막 비교
    e1rm_points = [p for p in points if p["best_e1rm"] is not None]
    if len(e1rm_points) < 2:
        base = (f"{canon} 기록이 조금 더 쌓이면 힘 추세를 보여드릴게요."
                if points else f"최근 {period_days}일 동안 {canon} 기록이 없어요.")
        return _with_persona(user_id, {
            "exercise": canon,
            "points": points,
            "e1rm_trend": {"direction": "flat", "pct_change": None},
            "note": base,
            "summary": base,
            "flag": "insufficient_data",
        })

    first = e1rm_points[0]["best_e1rm"]
    last = e1rm_points[-1]["best_e1rm"]
    direction = _direction(first, last, eps=first * 0.02)   # 2% 미만은 flat
    pct_change = round((last - first) / first * 100, 1) if first else None

    base = {
        "up":   f"{canon} 추정 1RM이 오르는 흐름이에요. 힘이 붙고 있어요.",
        "down": f"{canon} 추정 1RM이 내려가는 흐름이에요. 피로·컨디션이나 폼을 점검해봐요.",
        "flat": f"{canon} 추정 1RM은 대체로 유지 중이에요. 무게나 반복을 살짝 올려 자극을 줄 때.",
    }[direction]

    return _with_persona(user_id, {
        "exercise": canon,
        "points": points,
        "e1rm_trend": {"direction": direction, "pct_change": pct_change},
        "note": base,
        "summary": base,
        "flag": None,
    })


# ─────────────────────────────────────────────────────────────
# P2 — PR 추적 & 축하 (ExerciseSet 기반, estimate_1rm 공유)
# 기록 저장 시 종목별 과거 대비 신기록을 자동 감지 → 리텐션 도파민.
# ─────────────────────────────────────────────────────────────

# 노트 축하 문구를 고를 때의 우선순위(낮을수록 먼저).
_PR_PRIORITY = {"weight": 0, "e1rm": 1, "reps": 2, "volume": 3}


def _detect_prs(session, user_id: str, parsed: list[dict]) -> list[dict]:
    """이번 기록이 종목별 과거 대비 신기록(PR)인지 판정한다(P2).

    ExerciseSet(이미 저장된 과거분)만 조회해 '이전 최고'와 비교한다.
    ⚠️ 반드시 이번 세트를 session.add 하기 **전에** 호출해야 자기 자신과
    비교하지 않는다. 첫 기록(비교 대상 없음)은 PR 로 치지 않는다.

    감지 타입:
      - weight : 최고 중량 경신
      - e1rm   : 최고 추정 1RM 경신(Epley)
      - reps   : 동일 무게에서 최다 반복 경신
      - volume : 단일 세션 볼륨(Σ weight*reps) 경신

    반환: [{exercise, type, value, prev, unit, (weight)}]  (없으면 [])
    """
    # 이번 기록을 종목별로 모은다(같은 종목 여러 항목 가능).
    new_by_ex: dict[str, list[dict]] = defaultdict(list)
    for item in parsed or []:
        ex = item.get("exercise")
        if ex:
            new_by_ex[ex].append(item)

    prs: list[dict] = []
    for exercise, items in new_by_ex.items():
        # 이번 세션의 후보 신기록 집계(sets 만큼 전개된 것으로 간주).
        new_top_weight = None
        new_best_e1rm = None
        new_reps_at_weight: dict[float, int] = {}
        new_volume = 0.0
        for it in items:
            w = it.get("weight")
            r = it.get("reps")
            try:
                n_sets = max(1, int(it.get("sets")))
            except (TypeError, ValueError):
                n_sets = 1
            e = estimate_1rm(w, r)
            if e is not None and (new_best_e1rm is None or e > new_best_e1rm):
                new_best_e1rm = e
            if w is None:
                continue
            w = float(w)
            if new_top_weight is None or w > new_top_weight:
                new_top_weight = w
            if r:
                ri = int(r)
                new_volume += w * ri * n_sets
                if new_reps_at_weight.get(w, 0) < ri:
                    new_reps_at_weight[w] = ri

        # 이전 기록(ExerciseSet) 조회 — 워밍업 제외.
        rows = (
            session.query(ExerciseSet)
            .filter(ExerciseSet.user_id == user_id,
                    ExerciseSet.exercise == exercise,
                    ExerciseSet.is_warmup.isnot(True))
            .all()
        )
        if not rows:
            continue   # 첫 기록 → PR 아님

        prior_max_weight = None
        prior_max_e1rm = None
        prior_reps_at_weight: dict[float, int] = {}
        prior_volume_by_date: dict = defaultdict(float)
        for row in rows:
            w, r = row.weight, row.reps
            e = estimate_1rm(w, r)
            if e is not None and (prior_max_e1rm is None or e > prior_max_e1rm):
                prior_max_e1rm = e
            if w is None:
                continue
            w = float(w)
            if prior_max_weight is None or w > prior_max_weight:
                prior_max_weight = w
            if r:
                ri = int(r)
                prior_volume_by_date[row.date] += w * ri
                if prior_reps_at_weight.get(w, 0) < ri:
                    prior_reps_at_weight[w] = ri
        prior_max_volume = (max(prior_volume_by_date.values())
                            if prior_volume_by_date else None)

        # ── 판정 ──
        if (new_top_weight is not None and prior_max_weight is not None
                and new_top_weight > prior_max_weight):
            prs.append({"exercise": exercise, "type": "weight",
                        "value": round(new_top_weight, 1),
                        "prev": round(prior_max_weight, 1), "unit": "kg"})
        if (new_best_e1rm is not None and prior_max_e1rm is not None
                and new_best_e1rm > prior_max_e1rm):
            prs.append({"exercise": exercise, "type": "e1rm",
                        "value": round(new_best_e1rm, 1),
                        "prev": round(prior_max_e1rm, 1), "unit": "kg"})
        # 렙 PR: 예전에도 다뤄본 무게에서 반복수 경신(가장 큰 경신 하나만).
        best_rep_pr = None
        for w, reps in new_reps_at_weight.items():
            prev_reps = prior_reps_at_weight.get(w)
            if prev_reps is not None and reps > prev_reps:
                if best_rep_pr is None or reps - prev_reps > best_rep_pr[0]:
                    best_rep_pr = (reps - prev_reps, {
                        "exercise": exercise, "type": "reps",
                        "value": reps, "prev": prev_reps, "unit": "회",
                        "weight": round(w, 1)})
        if best_rep_pr:
            prs.append(best_rep_pr[1])
        if (new_volume > 0 and prior_max_volume is not None
                and new_volume > prior_max_volume):
            prs.append({"exercise": exercise, "type": "volume",
                        "value": round(new_volume, 1),
                        "prev": round(prior_max_volume, 1), "unit": "kg"})

    return prs


def pr_headline(prs: list[dict]) -> str:
    """감지된 PR 목록에서 노트에 붙일 축하 문구 한 줄을 만든다(페르소나 중립).

    가장 임팩트 큰 PR 하나를 헤드라인으로, 나머지는 개수로 요약한다.
    PR 이 없으면 빈 문자열.
    """
    if not prs:
        return ""
    top = min(prs, key=lambda p: _PR_PRIORITY.get(p["type"], 9))
    ex = top["exercise"]
    if top["type"] == "weight":
        head = f"🎉 {ex} 최고 중량 경신! {top['prev']}kg → {top['value']}kg"
    elif top["type"] == "e1rm":
        head = f"🎉 {ex} 추정 1RM 개인 최고 경신! 약 {top['value']}kg"
    elif top["type"] == "reps":
        head = (f"🎉 {ex} {top['weight']}kg 최다 반복 경신! "
                f"{top['prev']}회 → {top['value']}회")
    else:
        head = f"🎉 {ex} 세션 볼륨 최고 경신!"
    others = len(prs) - 1
    if others > 0:
        head += f" (그 외 기록 {others}개도 함께 경신했어요)"
    return head


# ─────────────────────────────────────────────────────────────
# P5 — 유지 레이어: 주간 리캡 · 목표 마일스톤 (ExerciseSet 기반)
# 재료(볼륨·부위균형·PR·e1RM)는 이미 있음 → 집계·요약·투영만.
# ─────────────────────────────────────────────────────────────

_WEEKLY_SET_LANDMARK = 10   # 부위별 주당 최소 세트 하한(routine과 동일 기준)


def _sets_in_window(user_id: str, start, end) -> list:
    """[start, end] 기간의 본세트(워밍업 제외) ExerciseSet 행."""
    session = SessionLocal()
    try:
        return (
            session.query(ExerciseSet)
            .filter(ExerciseSet.user_id == user_id,
                    ExerciseSet.date >= start, ExerciseSet.date <= end,
                    ExerciseSet.is_warmup.isnot(True))
            .all()
        )
    finally:
        session.close()


def _aggregate_week(rows) -> dict:
    """주간 세트 행 → 세션수·톤수·부위별 세트/볼륨 집계."""
    dates = set()
    tonnage = 0.0
    part_sets: dict[str, int] = {}
    part_volume: dict[str, float] = {}
    for r in rows:
        dates.add(r.date)
        part = log_name_to_part(r.exercise)
        if part:
            part_sets[part] = part_sets.get(part, 0) + 1
        if r.weight is not None and r.reps:
            vol = float(r.weight) * int(r.reps)
            tonnage += vol
            if part:
                part_volume[part] = part_volume.get(part, 0.0) + vol
    return {"sessions": len(dates), "tonnage": round(tonnage, 1),
            "part_sets": part_sets,
            "part_volume": {k: round(v, 1) for k, v in part_volume.items()}}


def _weekly_prs(user_id: str, start, end) -> list[dict]:
    """이 주에 종목별 역대 최고(중량 또는 e1RM)를 경신했는지 집계(P5).

    이번 주 최고를 start 이전 전체 기록의 최고와 비교한다(그 주가 신기록인가).
    """
    cur = _sets_in_window(user_id, start, end)
    by_ex_cur: dict[str, list] = defaultdict(list)
    for r in cur:
        by_ex_cur[r.exercise].append(r)

    session = SessionLocal()
    prs: list[dict] = []
    try:
        for exercise, rows in by_ex_cur.items():
            cur_w = max((float(r.weight) for r in rows if r.weight is not None),
                        default=None)
            cur_e = max((e for r in rows
                         if (e := estimate_1rm(r.weight, r.reps)) is not None),
                        default=None)
            prior = (session.query(ExerciseSet)
                     .filter(ExerciseSet.user_id == user_id,
                             ExerciseSet.exercise == exercise,
                             ExerciseSet.date < start,
                             ExerciseSet.is_warmup.isnot(True)).all())
            if not prior:
                continue   # 이번 주가 첫 등장 → PR 아님
            prior_w = max((float(r.weight) for r in prior
                           if r.weight is not None), default=None)
            prior_e = max((e for r in prior
                           if (e := estimate_1rm(r.weight, r.reps)) is not None),
                          default=None)
            if cur_w is not None and prior_w is not None and cur_w > prior_w:
                prs.append({"exercise": exercise, "type": "weight",
                            "value": round(cur_w, 1), "prev": round(prior_w, 1)})
            elif cur_e is not None and prior_e is not None and cur_e > prior_e:
                prs.append({"exercise": exercise, "type": "e1rm",
                            "value": round(cur_e, 1), "prev": round(prior_e, 1)})
    finally:
        session.close()
    return prs


def get_weekly_recap(user_id: str, week_offset: int = 0) -> dict:
    """주간 리캡(P5): 세션수·총 톤수·부위별 볼륨 Δ·신규 PR·미달 부위·넛지.

    week_offset=0 은 최근 7일, 1은 그 이전 7일. 이전 주와 비교해 톤수 변화와
    보완 부위를 짚는다. 응답 note/nudges 를 사용자에게 전달한다.
    """
    today = datetime.now().date()
    end = today - timedelta(days=7 * week_offset)
    start = end - timedelta(days=6)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)

    cur = _aggregate_week(_sets_in_window(user_id, start, end))
    prev = _aggregate_week(_sets_in_window(user_id, prev_start, prev_end))
    prs = _weekly_prs(user_id, start, end)

    tonnage_delta = round(cur["tonnage"] - prev["tonnage"], 1)
    under_target = sorted(
        p for p in cur["part_sets"] if cur["part_sets"][p] < _WEEKLY_SET_LANDMARK)

    nudges: list[str] = []
    if cur["sessions"] == 0:
        base = "이번 주엔 아직 운동 기록이 없어요. 가볍게라도 한 세션 남겨볼까요?"
        nudges.append("이번 주 운동 기록이 비어 있어요. 30분이라도 움직여봐요.")
        flag = "no_sessions"
    else:
        parts = [f"세션 {cur['sessions']}회", f"총 볼륨 {cur['tonnage']:g}"]
        if prev["sessions"]:
            trend_word = ("늘었어요" if tonnage_delta > 0
                          else "줄었어요" if tonnage_delta < 0 else "비슷해요")
            parts.append(f"지난주 대비 볼륨이 {trend_word}")
        base = "이번 주 리캡 — " + ", ".join(parts) + "."
        if prs:
            base += f" 신기록 {len(prs)}개를 세웠어요! 🎉"
        if under_target:
            nudges.append(
                f"{'·'.join(under_target)} 볼륨이 주당 권장({_WEEKLY_SET_LANDMARK}세트)"
                "에 못 미쳐요. 다음 세션에서 보완하면 좋아요.")
        flag = None

    return _with_persona(user_id, {
        "week_offset": week_offset,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "sessions": cur["sessions"],
        "tonnage": cur["tonnage"],
        "tonnage_delta": tonnage_delta,
        "part_volume": cur["part_volume"],
        "part_sets": cur["part_sets"],
        "new_prs": prs,
        "under_target_parts": under_target,
        "nudges": nudges,
        "summary": base,
        "note": base,
        "flag": flag,
    })


def get_goal_projection(user_id: str, exercise: str, target_weight: float,
                        by_date: str | None = None) -> dict:
    """목표 마일스톤 투영(P5): 현재 추정 1RM + 최근 상승률로 도달 예상일.

    "9월까지 벤치 100kg" → 최근 e1RM 시계열의 주당 상승률로 target_weight(1RM)
    도달 시점을 선형 투영한다. by_date(YYYY-MM-DD) 주면 그 전에 닿을지(on_track).
    상승률이 0 이하면 투영 불가(더 밀어야 함).
    """
    canon = normalize_exercise(exercise)
    today = datetime.now().date()
    points = _exercise_series(user_id, exercise, today - timedelta(days=90))
    e1rm_points = [p for p in points if p["best_e1rm"] is not None]

    def _wrap(note, **extra):
        return _with_persona(user_id, {
            "exercise": canon, "target_weight": target_weight,
            "note": note, "summary": note, **extra})

    if not e1rm_points:
        return _wrap(f"{canon} 기록이 아직 없어요. 몇 번 기록하면 도달 예상일을 잡아볼게요.",
                     current_e1rm=None, projected_date=None,
                     on_track=None, flag="insufficient_data")

    current = e1rm_points[-1]["best_e1rm"]
    if current >= target_weight:
        return _wrap(f"이미 {canon} 추정 1RM {current:g}kg로 목표 {target_weight:g}kg를 "
                     "넘었어요! 새 목표를 잡아봐요.",
                     current_e1rm=current, projected_date=None,
                     on_track=True, flag="achieved")

    if len(e1rm_points) < 2:
        return _wrap(f"{canon} 상승 추세를 보려면 기록이 조금 더 필요해요.",
                     current_e1rm=current, projected_date=None,
                     on_track=None, flag="insufficient_data")

    first = e1rm_points[0]
    last = e1rm_points[-1]
    span_days = (_date.fromisoformat(last["date"])
                 - _date.fromisoformat(first["date"])).days
    if span_days <= 0:
        rate_per_week = 0.0
    else:
        rate_per_week = (last["best_e1rm"] - first["best_e1rm"]) / span_days * 7

    if rate_per_week <= 0:
        return _wrap(f"{canon} 추정 1RM이 최근 정체·하락 흐름이라 지금 속도로는 목표 "
                     f"{target_weight:g}kg 도달 시점을 잡기 어려워요. 자극·회복을 점검해봐요.",
                     current_e1rm=current, rate_per_week=round(rate_per_week, 2),
                     projected_date=None, on_track=False, flag="stalled")

    weeks_needed = (target_weight - current) / rate_per_week
    projected = today + timedelta(days=round(weeks_needed * 7))
    note = (f"{canon} 추정 1RM {current:g}kg, 최근 주당 약 {rate_per_week:.1f}kg 상승 중 "
            f"→ 목표 {target_weight:g}kg는 {projected.isoformat()}쯤 도달 예상이에요.")
    on_track = None
    if by_date:
        try:
            deadline = _date.fromisoformat(by_date)
            on_track = projected <= deadline
            note += (" 목표 시점 안에 충분히 닿을 페이스예요." if on_track
                     else " 목표 시점보단 조금 늦을 수 있어 볼륨을 더 올려볼까요?")
        except ValueError:
            pass
    return _wrap(note, current_e1rm=current,
                 rate_per_week=round(rate_per_week, 2),
                 projected_date=projected.isoformat(),
                 on_track=on_track, flag=None)
