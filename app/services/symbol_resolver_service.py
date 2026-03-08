import re
from collections import defaultdict
from functools import lru_cache
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from app.common.http_client import get_http_client
from app.common.symbol_utils import extract_explicit_symbol, normalize_symbol, to_stooq_symbol
try:
    from duckduckgo_search import DDGS
except Exception:
    DDGS = None


class SymbolResolverService:
    def __init__(self) -> None:
        self._headers = {"User-Agent": "Mozilla/5.0"}
        self._http_client = get_http_client()
        self._token_stopwords = {
            "HTTP",
            "HTTPS",
            "WWW",
            "COM",
            "CN",
            "NET",
            "ORG",
            "CO",
            "HK",
            "US",
            "YAHOO",
            "FINANCE",
            "QUOTE",
            "PRICE",
            "STOCK",
            "GROUP",
            "INC",
            "LTD",
            "ADR",
            "ETF",
            "NASDAQ",
            "NYSE",
            "OTC",
            "W",
            "CLASS",
            "THE",
            "AND",
            "FOR",
            "WITH",
            "FROM",
            "NEWS",
            "OTHER",
            "HELP",
            "YOU",
            "YOUR",
            "ALL",
            "THIS",
            "THAT",
            "WAS",
            "ARE",
            "CAN",
            "NOT",
            "NEW",
            "GET",
            "HAS",
            "HAVE",
            "TOP",
            "TODAY",
            "MARKET",
            "SHARE",
            "CHART",
            "INDEX",
            "DATA",
            "LIST",
            "HTML",
        }
        self._asset_words = [
            "近期",
            "最近",
            "当前",
            "现在",
            "今日",
            "昨天",
            "股价",
            "涨跌",
            "走势",
            "行情",
            "情况",
            "如何",
            "为什么",
            "为何",
            "多少",
            "查询",
            "分析",
            "近",
            "天",
            "日",
            "月",
            "年",
            "的",
        ]

    def resolve(self, question: str) -> Optional[str]:
        explicit = extract_explicit_symbol(question)
        if explicit:
            return explicit

        entity_query = self._extract_entity_query(question)
        if not entity_query:
            return None

        return self._resolve_by_query(entity_query)

    @lru_cache(maxsize=1024)
    def _resolve_by_query(self, query: str) -> Optional[str]:
        scored_candidates = defaultdict(float)

        for symbol, score in self._search_eastmoney(query):
            scored_candidates[normalize_symbol(symbol)] += score + 3.0

        for symbol, score in self._search_yahoo(query):
            scored_candidates[normalize_symbol(symbol)] += score + 2.0

        if not scored_candidates:
            for symbol, score in self._search_web(query):
                scored_candidates[normalize_symbol(symbol)] += score + 1.0

        if not scored_candidates:
            return None

        ranked = sorted(scored_candidates.items(), key=lambda x: x[1], reverse=True)
        for symbol, _ in ranked[:8]:
            if self._is_valid_symbol(symbol):
                return symbol

        return ranked[0][0] if ranked else None

    def _search_eastmoney(self, query: str) -> List[Tuple[str, float]]:
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {
            "input": query,
            "type": "14",
            "count": "30",
            "token": "D43BF722C8E33BDC906FB84D85E326E8",
        }
        payload = self._http_client.get_json(url, params=params, headers=self._headers, timeout=8.0)
        if payload is None:
            return []
        rows = payload.get("QuotationCodeTable", {}).get("Data", []) or []
        result: List[Tuple[str, float]] = []
        for item in rows:
            classify = str(item.get("Classify", "") or "")
            code = str(item.get("Code", "") or "").upper()
            symbol = self._format_eastmoney_symbol(code, classify)
            if not symbol:
                continue

            name = str(item.get("Name", "") or "")
            exchange = str(item.get("JYS", "") or "").upper()
            score = 10.0
            if exchange in {"NASDAQ", "NYSE", "HK"}:
                score += 3.0
            if query and query in name:
                score += 3.0
            if any(flag in name for flag in ["ETF", "期权", "期货", "做多", "做空", "杠杆"]):
                score -= 4.0
            result.append((symbol, score))
        return result

    def _extract_entity_query(self, question: str) -> str:
        query = re.sub(r"[，。！？、,.!?()（）【】\\[\\]{}:：;；/\\\\]", " ", question)
        query = re.sub(r"\d+\s*(天|日|月|年)", " ", query)
        for word in self._asset_words:
            query = query.replace(word, " ")
        query = re.sub(r"\s+", " ", query).strip()
        if not query:
            return ""
        parts = [part.strip() for part in query.split(" ") if part.strip()]
        if not parts:
            return ""
        return parts[0][:32]

    def _search_yahoo(self, query: str) -> List[Tuple[str, float]]:
        params = {
            "q": query,
            "quotesCount": 10,
            "newsCount": 0,
            "region": "US",
            "lang": "en-US",
        }
        url = "https://query1.finance.yahoo.com/v1/finance/search"

        payload = self._http_client.get_json(url, params=params, headers=self._headers, timeout=10.0)
        if payload is None:
            return []
        quotes = payload.get("quotes", []) or []
        result: List[Tuple[str, float]] = []
        for item in quotes:
            if item.get("quoteType") != "EQUITY":
                continue
            symbol = item.get("symbol", "")
            if not symbol:
                continue
            score = float(item.get("score", 0.0) or 0.0)
            result.append((symbol, score))
        return result

    def _search_web(self, query: str) -> List[Tuple[str, float]]:
        if DDGS is None:
            return []

        score_map: Dict[str, float] = defaultdict(float)
        queries = [f"{query} 股票代码", f"{query} ticker"]
        for idx, search_query in enumerate(queries):
            try:
                with DDGS() as ddgs:
                    results = list(ddgs.text(search_query, max_results=4))
            except Exception:
                continue

            for item in results:
                text = " ".join(
                    [
                        str(item.get("title", "")),
                        str(item.get("body", "")),
                        str(item.get("href", "")),
                    ]
                )
                for symbol in self._extract_symbols_from_text(text):
                    bonus = 2.5 if symbol.endswith(".HK") else 1.0
                    score_map[symbol] += max(1.0, 4.0 - idx) + bonus

        ranked = sorted(score_map.items(), key=lambda x: x[1], reverse=True)
        return ranked

    def _extract_symbols_from_text(self, text: str) -> List[str]:
        candidates = set()
        normalized = text.upper()
        normalized = re.sub(r"HTTPS?://\\S+", " ", normalized)
        normalized = re.sub(r"\\bWWW\\.[^\\s]+", " ", normalized)

        for sym in re.findall(r"\b0?\d{3,5}\.HK\b", normalized):
            candidates.add(normalize_symbol(sym))

        for sym in re.findall(r"\b[A-Z]{2,5}\b", normalized):
            if sym in self._token_stopwords or sym in {"USD", "CNY", "RMB"}:
                continue
            candidates.add(sym)

        for hk_code in re.findall(r"\((0?\d{3,5})\)", normalized):
            if "HK" in normalized or "港股" in text:
                candidates.add(normalize_symbol(f"{hk_code}.HK"))

        return list(candidates)

    @lru_cache(maxsize=2048)
    def _is_valid_symbol(self, symbol: str) -> bool:
        stooq_symbol = to_stooq_symbol(symbol)
        url = f"https://stooq.com/q/l/?s={quote(stooq_symbol)}&i=d"
        raw_response = self._http_client.get_text(url, headers=self._headers, timeout=4.5)
        if not raw_response:
            return False
        raw = raw_response.strip()
        if not raw or "No data" in raw:
            return False
        line = raw.splitlines()[0].strip()
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 7:
            return False
        close_val = parts[6] if len(parts) > 6 else ""
        return bool(close_val and close_val.lower() != "nan")

    def _format_eastmoney_symbol(self, code: str, classify: str) -> Optional[str]:
        if classify == "HK":
            if not code.isdigit():
                return None
            if int(code) > 9999:
                return None
            return f"{int(code):04d}.HK"

        if classify == "UsStock":
            if re.fullmatch(r"[A-Z]{1,5}", code):
                return code
            return None

        return None
