


# ── 볼륨 계산 ──────────────────────────────────────────────
def session_volume(parsed) -> float:
    """한 세션 parsed에서 Σ(weight×sets×reps). None 항목은 skip."""
    if not parsed:
        return 0.0
    total = 0.0
    for item in parsed:
        w, s, r = item.get("weight"), item.get("sets"), item.get("reps")
        if w is None or s is None or r is None:
            continue            # 맨몸/누락은 볼륨에서 제외
        total += w * s * r
    return total