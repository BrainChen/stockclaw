import re
from typing import Optional


def normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized.endswith(".HK"):
        digits = normalized.split(".")[0]
        if digits.isdigit():
            return f"{int(digits):04d}.HK"
    return normalized


def to_stooq_symbol(symbol: str) -> str:
    normalized = symbol.strip().lower()
    if normalized.endswith(".hk"):
        base = normalized.split(".")[0]
        if base.isdigit():
            base = str(int(base))
        return f"{base}.hk"
    if normalized.endswith(".us"):
        return normalized
    if normalized.isalpha():
        return f"{normalized}.us"
    return normalized


def extract_explicit_symbol(question: str) -> Optional[str]:
    ticker_match = re.findall(r"\b[A-Z]{1,5}(?:\.[A-Z]{1,3})?\b", question.upper())
    if ticker_match:
        return normalize_symbol(ticker_match[0])

    hk_match = re.findall(r"\b0?\d{3,5}\.HK\b", question.upper())
    if hk_match:
        return normalize_symbol(hk_match[0])

    code_match = re.search(r"(?:代码|ticker|symbol|股票)\s*[:：]?\s*(0?\d{3,5})\b", question, re.IGNORECASE)
    if code_match:
        return normalize_symbol(f"{code_match.group(1)}.HK")
    return None
