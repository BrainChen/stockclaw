import datetime as dt
import json
import re
from typing import Optional

from app.common.logger import get_logger, kv, preview_text
from app.common.market_rules import is_large_move_question
from app.common.symbol_utils import extract_explicit_symbol, normalize_symbol
from app.core.config import get_settings
from app.models.query_dsl import QueryDSL
from app.services.layers.integration.llm_service import LLMService
from app.services.layers.routing.router_service import QueryRouter
from app.services.layers.asset.symbol_resolver_service import SymbolResolverService


class QueryInterpreterService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.router = QueryRouter()
        self.symbol_resolver = SymbolResolverService()
        self.llm_service = LLMService()
        self.logger = get_logger(__name__)
        self._metrics_map = {
            "close": ["收盘", "收盘价", "价格", "价位", "close", "price"],
            "change": ["涨跌", "涨幅", "跌幅", "回报", "收益", "return", "change"],
            "trend": ["走势", "趋势", "k线", "k 线", "trend"],
            "volatility": ["波动", "波动率", "volatility"],
            "volume": ["成交量", "换手", "volume"],
        }
        self._allowed_metrics = {"close", "change", "trend", "volatility", "volume", "event"}
        self._news_keywords = [
            "为什么",
            "为何",
            "原因",
            "新闻",
            "消息",
            "财报",
            "宏观",
        ]
        self._window_patterns: list[tuple[re.Pattern[str], int]] = [
            (re.compile(r"(最近|近|过去)?\s*一?\s*周"), 7),
            (re.compile(r"(最近|近|过去)?\s*(两|2)\s*周"), 14),
            (re.compile(r"(最近|近|过去)?\s*一?\s*个月"), 30),
            (re.compile(r"(最近|近|过去)?\s*(三|3)\s*个月"), 90),
            (re.compile(r"(最近|近|过去)?\s*半年"), 120),
            (re.compile(r"(最近|近期|近来|短期|这段时间)"), 7),
            (re.compile(r"(中期)"), 30),
        ]

    def parse(self, question: str) -> QueryDSL:
        fallback_dsl = self._parse_rule_based(question)
        self.logger.info(
            "dsl rule parsed %s",
            kv(question=preview_text(question, max_len=100), dsl=fallback_dsl.to_expression()),
        )
        if self._should_return_api_first(fallback_dsl):
            self.logger.info("dsl api-first short-circuit %s", kv(dsl=fallback_dsl.to_expression()))
            return fallback_dsl
        if self.settings.query_interpreter_use_llm and self.llm_service.enabled:
            self.logger.info("dsl llm parsing start %s", kv(question=preview_text(question, max_len=100)))
            llm_dsl = self._parse_with_llm(question=question, fallback_dsl=fallback_dsl)
            if llm_dsl is not None:
                self.logger.info("dsl llm parsed %s", kv(dsl=llm_dsl.to_expression()))
                return llm_dsl
            self.logger.warning("dsl llm parse failed, use fallback %s", kv(dsl=fallback_dsl.to_expression()))
        return fallback_dsl

    def _should_return_api_first(self, dsl: QueryDSL) -> bool:
        if dsl.route != "asset":
            return False
        if not dsl.symbol:
            return False
        explicit_symbol = extract_explicit_symbol(dsl.question)
        if explicit_symbol:
            return True
        if dsl.event_date is not None:
            return True
        has_explicit_window = bool(re.search(r"\d{1,3}\s*(天|日|周|个月|月)", dsl.question))
        if has_explicit_window and dsl.window_days is not None:
            return True
        return False

    def _parse_rule_based(self, question: str) -> QueryDSL:
        route_result = self.router.route(question)
        if route_result.route == "knowledge":
            return QueryDSL(
                route="knowledge",
                question=question,
                confidence=0.85,
            )

        symbol = route_result.symbol or self.symbol_resolver.resolve(question)
        event_date = self._extract_date(question)
        window_days, window_confidence = self._extract_window_days(question)
        metrics = self._extract_metrics(question, event_date)
        need_news = event_date is not None or self._contains_any(question, self._news_keywords)
        check_large_move = is_large_move_question(question)

        confidence = 0.55
        if symbol:
            confidence += 0.25
        if window_days is not None:
            confidence += window_confidence
        if event_date is not None:
            confidence += 0.1
        confidence = max(0.0, min(confidence, 0.99))

        return QueryDSL(
            route="asset",
            question=question,
            symbol=symbol,
            window_days=window_days,
            event_date=event_date,
            metrics=metrics,
            need_news=need_news,
            check_large_move=check_large_move,
            confidence=confidence,
        )

    def _parse_with_llm(self, question: str, fallback_dsl: QueryDSL) -> Optional[QueryDSL]:
        today = dt.date.today().isoformat()
        system_prompt = (
            "你是金融查询 DSL 解释器。"
            "请将用户问题转换为严格 JSON，不要输出 Markdown、不要输出额外解释。"
            "字段必须包含：route, symbol, window_days, event_date, metrics, need_news, check_large_move, confidence。"
            "route 只能是 asset 或 knowledge。"
            "window_days 必须是 1-120 的整数或 null。"
            "event_date 必须是 YYYY-MM-DD 或 null。"
            'metrics 只能从 ["close","change","trend","volatility","volume","event"] 选择。'
            "confidence 范围是 0 到 1。"
        )
        user_prompt = (
            f"今天日期：{today}\n"
            f"用户问题：{question}\n"
            f"规则引擎初始结果（供你参考，可修正）：{fallback_dsl.to_dict()}\n"
            "请只输出 JSON。"
        )
        llm_text = self.llm_service.generate(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.0)
        if not llm_text:
            self.logger.warning("dsl llm empty response")
            return None
        payload = self._extract_json_payload(llm_text)
        if payload is None:
            self.logger.warning("dsl llm invalid json %s", kv(raw=preview_text(llm_text, max_len=180)))
            return None
        return self._coerce_llm_dsl(payload=payload, question=question, fallback_dsl=fallback_dsl)

    def _extract_json_payload(self, llm_text: str) -> Optional[dict]:
        content = llm_text.strip()
        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL | re.IGNORECASE)
        if fenced_match:
            content = fenced_match.group(1).strip()
        else:
            bracket_match = re.search(r"\{.*\}", content, re.DOTALL)
            if bracket_match:
                content = bracket_match.group(0).strip()
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _coerce_llm_dsl(self, payload: dict, question: str, fallback_dsl: QueryDSL) -> QueryDSL:
        route_raw = payload.get("route")
        route = route_raw if route_raw in {"asset", "knowledge"} else fallback_dsl.route

        symbol_raw = payload.get("symbol")
        symbol: Optional[str]
        if isinstance(symbol_raw, str) and symbol_raw.strip():
            symbol = normalize_symbol(symbol_raw.strip())
        elif symbol_raw is None:
            symbol = None
        else:
            symbol = fallback_dsl.symbol

        window_raw = payload.get("window_days")
        window_days: Optional[int] = None
        if isinstance(window_raw, bool):
            window_days = fallback_dsl.window_days
        elif isinstance(window_raw, int):
            window_days = window_raw if 1 <= window_raw <= 120 else fallback_dsl.window_days
        elif isinstance(window_raw, float) and window_raw.is_integer():
            candidate = int(window_raw)
            window_days = candidate if 1 <= candidate <= 120 else fallback_dsl.window_days
        elif window_raw is None:
            window_days = None
        else:
            window_days = fallback_dsl.window_days

        event_date_raw = payload.get("event_date")
        event_date: Optional[dt.date] = None
        if isinstance(event_date_raw, str) and event_date_raw.strip():
            try:
                event_date = dt.date.fromisoformat(event_date_raw.strip())
            except Exception:
                event_date = fallback_dsl.event_date
        elif event_date_raw is None:
            event_date = None
        else:
            event_date = fallback_dsl.event_date

        metrics_raw = payload.get("metrics")
        metrics: list[str] = []
        if isinstance(metrics_raw, list):
            for item in metrics_raw:
                if not isinstance(item, str):
                    continue
                metric = item.strip().lower()
                if metric in self._allowed_metrics and metric not in metrics:
                    metrics.append(metric)
        if not metrics:
            metrics = fallback_dsl.metrics

        need_news_raw = payload.get("need_news")
        need_news = need_news_raw if isinstance(need_news_raw, bool) else fallback_dsl.need_news

        large_move_raw = payload.get("check_large_move")
        check_large_move = large_move_raw if isinstance(large_move_raw, bool) else fallback_dsl.check_large_move

        confidence_raw = payload.get("confidence")
        confidence = fallback_dsl.confidence
        if isinstance(confidence_raw, (float, int)) and not isinstance(confidence_raw, bool):
            confidence = max(0.0, min(float(confidence_raw), 1.0))

        if route == "knowledge":
            return QueryDSL(
                route="knowledge",
                question=question,
                symbol=None,
                window_days=None,
                event_date=None,
                metrics=[],
                need_news=False,
                check_large_move=False,
                confidence=confidence,
            )

        resolved_symbol = symbol or fallback_dsl.symbol
        return QueryDSL(
            route="asset",
            question=question,
            symbol=resolved_symbol,
            window_days=window_days,
            event_date=event_date,
            metrics=metrics,
            need_news=need_news,
            check_large_move=check_large_move,
            confidence=confidence,
        )

    def _extract_window_days(self, question: str) -> tuple[Optional[int], float]:
        normalized = (
            question.replace("个交易日", "天")
            .replace("交易日", "天")
            .replace(" 日", "天")
            .strip()
        )
        explicit_match = re.search(r"(?:最近|近|过去)?\s*(\d{1,3})\s*天", normalized)
        if explicit_match:
            days = int(explicit_match.group(1))
            if 1 <= days <= 120:
                return days, 0.12

        for pattern, days in self._window_patterns:
            if pattern.search(normalized):
                return days, 0.08
        return None, 0.0

    def _extract_date(self, question: str) -> Optional[dt.date]:
        full_match = re.search(
            r"((?:19|20)\d{2})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})\s*日?",
            question,
        )
        if full_match:
            year = int(full_match.group(1))
            month = int(full_match.group(2))
            day = int(full_match.group(3))
            try:
                return dt.date(year, month, day)
            except ValueError:
                return None

        short_match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", question)
        if not short_match:
            return None
        month = int(short_match.group(1))
        day = int(short_match.group(2))
        today = dt.date.today()
        year = today.year
        try:
            candidate = dt.date(year, month, day)
            if candidate > today:
                candidate = dt.date(year - 1, month, day)
            return candidate
        except ValueError:
            return None

    def _extract_metrics(self, question: str, event_date: Optional[dt.date]) -> list[str]:
        lowered = question.lower()
        metrics: list[str] = []
        for metric_name, keywords in self._metrics_map.items():
            if any(keyword in lowered for keyword in keywords):
                metrics.append(metric_name)
        if event_date and "event" not in metrics:
            metrics.append("event")
        if not metrics:
            metrics = ["change", "trend", "volatility"]
        return metrics

    def _contains_any(self, text: str, keywords: list[str]) -> bool:
        lowered = text.lower()
        return any(keyword.lower() in lowered for keyword in keywords)
