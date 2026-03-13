import re
from typing import Optional


def _infer_a_share_suffix(code: str) -> Optional[str]:
    if not re.fullmatch(r"\d{6}", code):
        return None
    if code.startswith(("6", "9")):
        return "SS"
    if code.startswith(("0", "2", "3")):
        return "SZ"
    return None


def _infer_hk_symbol(code: str) -> Optional[str]:
    if not re.fullmatch(r"\d{4,5}", code):
        return None
    return f"{int(code):04d}.HK"


def normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    hk_match = re.fullmatch(r"(0?\d{3,5})[\s\-_/.]*HK", normalized)
    if hk_match:
        return f"{int(hk_match.group(1)):04d}.HK"
    a_share_match = re.fullmatch(r"(\d{6})[\s\-_/.]*(SH|SS|SZ)", normalized)
    if a_share_match:
        code = a_share_match.group(1)
        suffix = a_share_match.group(2).replace("SH", "SS")
        return f"{code}.{suffix}"
    inferred_hk_symbol = _infer_hk_symbol(normalized)
    if inferred_hk_symbol:
        return inferred_hk_symbol
    if normalized.endswith(".HK"):
        digits = normalized.split(".")[0]
        if digits.isdigit():
            return f"{int(digits):04d}.HK"
    if re.fullmatch(r"\d{6}\.SH", normalized):
        return normalized.replace(".SH", ".SS")
    if re.fullmatch(r"\d{6}\.(SS|SZ)", normalized):
        return normalized
    inferred_suffix = _infer_a_share_suffix(normalized)
    if inferred_suffix:
        return f"{normalized}.{inferred_suffix}"
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
    if re.fullmatch(r"\d{6}\.(ss|sz|sh)", normalized):
        base = normalized.split(".")[0]
        return f"{base}.cn"
    if normalized.isalpha():
        return f"{normalized}.us"
    return normalized


def is_a_share_symbol(symbol: str) -> bool:
    normalized = normalize_symbol(symbol)
    return bool(re.fullmatch(r"\d{6}\.(SS|SZ)", normalized))


def to_eastmoney_secid(symbol: str) -> Optional[str]:
    normalized = normalize_symbol(symbol)
    if not is_a_share_symbol(normalized):
        return None
    code, suffix = normalized.split(".")
    market = "1" if suffix == "SS" else "0"
    return f"{market}.{code}"


def extract_explicit_symbol(question: str) -> Optional[str]:
    a_share_match = re.findall(r"\b\d{6}\.(?:SH|SS|SZ)\b", question.upper())
    if a_share_match:
        return normalize_symbol(a_share_match[0])

    hk_match = re.findall(r"\b0?\d{3,5}\.HK\b", question.upper())
    if hk_match:
        return normalize_symbol(hk_match[0])

    ticker_match = re.findall(r"(?<!\.)\b[A-Z]{1,5}(?:\.[A-Z]{1,3})?\b", question.upper())
    if ticker_match:
        return normalize_symbol(ticker_match[0])

    code_match = re.search(r"(?:代码|ticker|symbol|股票)\s*[:：]?\s*(\d{3,6})\b", question, re.IGNORECASE)
    if code_match:
        raw_code = code_match.group(1)
        if len(raw_code) == 6:
            return normalize_symbol(raw_code)
        return normalize_symbol(f"{raw_code}.HK")

    has_a_share_context = bool(
        re.search(
            r"(A股|沪深|上证|深证|A\s*share|A-share|股票|股价|涨跌|走势|行情|收盘|开盘|成交量)",
            question,
            re.IGNORECASE,
        )
    )
    generic_a_share_code = re.search(r"\b([02369]\d{5})\b", question)
    if has_a_share_context and generic_a_share_code:
        return normalize_symbol(generic_a_share_code.group(1))
    return None
