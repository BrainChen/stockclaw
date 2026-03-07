import re
from dataclasses import dataclass
from typing import Literal, Optional

from app.services.symbol_resolver_service import SymbolResolverService


RouteType = Literal["asset", "knowledge"]


@dataclass
class RouteResult:
    route: RouteType
    symbol: Optional[str] = None


class QueryRouter:
    def __init__(self) -> None:
        self.symbol_resolver = SymbolResolverService()
        self.asset_keywords = [
            "股价",
            "涨跌",
            "走势",
            "行情",
            "k线",
            "价格",
            "ticker",
            "股票",
            "大涨",
            "大跌",
            "7天",
            "30天",
            "7 日",
            "30 日",
        ]
        self.knowledge_keywords = [
            "什么是",
            "区别",
            "定义",
            "财报摘要",
            "解释",
            "概念",
            "市盈率",
            "净利润",
            "收入",
            "roe",
            "roa",
            "eps",
        ]

    def route(self, question: str) -> RouteResult:
        lowered = question.lower()
        explicit_symbol = self._extract_explicit_symbol(question)
        has_asset_keyword = any(keyword in lowered for keyword in self.asset_keywords)
        has_knowledge_keyword = any(keyword in lowered for keyword in self.knowledge_keywords)

        if explicit_symbol:
            return RouteResult(route="asset", symbol=explicit_symbol)
        if has_asset_keyword:
            symbol = self.extract_symbol(question)
            return RouteResult(route="asset", symbol=symbol)
        if has_knowledge_keyword:
            return RouteResult(route="knowledge")
        return RouteResult(route="knowledge")

    def extract_symbol(self, question: str) -> Optional[str]:
        return self.symbol_resolver.resolve(question)

    def _extract_explicit_symbol(self, question: str) -> Optional[str]:
        ticker_match = re.findall(r"\b[A-Z]{1,5}(?:\.[A-Z]{1,3})?\b", question.upper())
        if ticker_match:
            return ticker_match[0]
        hk_match = re.findall(r"\b0?\d{3,5}\.HK\b", question.upper())
        if hk_match:
            code = hk_match[0].split(".")[0]
            return f"{int(code):04d}.HK"
        return None
