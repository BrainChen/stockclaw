import re
from dataclasses import dataclass
from typing import Literal, Optional

from app.services.layers.asset.symbol_resolver_service import SymbolResolverService
from app.common.symbol_utils import extract_explicit_symbol


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
            "基金",
            "指数",
            "成交量",
            "收盘价",
            "开盘价",
            "盘前",
            "盘中",
            "盘后",
            "盘尾",
            "分时",
            "最高价",
            "最低价",
            "回撤",
            "波动率",
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
            "原理",
            "逻辑",
            "估值",
            "财务报表",
            "资产配置",
            "风险管理",
            "久期",
            "凸性",
            "对冲",
            "roe",
            "roa",
            "eps",
        ]
        self.market_pattern = re.compile(
            r"(最近|近|过去)?\s*\d{1,3}\s*(天|日|个交易日)|"
            r"(涨跌|行情|走势|收盘|开盘|盘前|盘中|盘后|盘尾|分时|最高|最低|成交量|波动|回撤|市值|股价)"
        )
        self.knowledge_pattern = re.compile(
            r"(什么是|如何理解|为什么|区别|定义|概念|框架|原理|影响机制|估值方法|财报解读)"
        )

    def route(self, question: str) -> RouteResult:
        cleaned_question = question.strip()
        lowered = cleaned_question.lower()
        explicit_symbol = self._extract_explicit_symbol(cleaned_question)
        has_asset_keyword = any(keyword in lowered for keyword in self.asset_keywords) or bool(
            self.market_pattern.search(cleaned_question)
        )
        has_knowledge_keyword = any(keyword in lowered for keyword in self.knowledge_keywords) or bool(
            self.knowledge_pattern.search(cleaned_question)
        )

        if explicit_symbol:
            return RouteResult(route="asset", symbol=explicit_symbol)
        if has_asset_keyword:
            symbol = self.extract_symbol(cleaned_question)
            if symbol:
                return RouteResult(route="asset", symbol=symbol)
            if has_knowledge_keyword:
                return RouteResult(route="knowledge")
            return RouteResult(route="asset", symbol=symbol)
        if has_knowledge_keyword:
            return RouteResult(route="knowledge")
        return RouteResult(route="knowledge")

    def extract_symbol(self, question: str) -> Optional[str]:
        return self.symbol_resolver.resolve(question)

    def _extract_explicit_symbol(self, question: str) -> Optional[str]:
        return extract_explicit_symbol(question)
