LARGE_MOVE_QUESTION_KEYWORDS = ("大涨", "暴涨", "大跌", "暴跌", "急涨", "急跌", "跳涨", "跳水")


def normalize_large_move_threshold(threshold_pct: float | int | None, default: float = 3.0) -> float:
    if threshold_pct is None:
        return default
    try:
        threshold = float(threshold_pct)
        if threshold <= 0:
            return default
        return threshold
    except Exception:
        return default


def is_large_move_question(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(keyword in lowered for keyword in LARGE_MOVE_QUESTION_KEYWORDS)


def is_large_move(change_pct: float | int, threshold_pct: float | int | None = 3.0) -> bool:
    threshold = normalize_large_move_threshold(threshold_pct=threshold_pct, default=3.0)
    try:
        return abs(float(change_pct)) >= threshold
    except Exception:
        return False
