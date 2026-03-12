import datetime as dt
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf

from app.common.market_rules import (
    is_large_move,
    is_large_move_question,
    normalize_large_move_threshold,
)


class NewsAnalyzerService:
    def __init__(self, large_move_threshold_pct: float) -> None:
        self.large_move_threshold_pct = normalize_large_move_threshold(
            large_move_threshold_pct,
            default=3.0,
        )

    def fetch_news(self, ticker: yf.Ticker, symbol: str) -> List[Dict[str, Any]]:
        try:
            raw_news = getattr(ticker, "news", []) or []
        except Exception:
            raw_news = []
        result: List[Dict[str, Any]] = []
        for item in raw_news[:10]:
            publish_ts = item.get("providerPublishTime")
            published_at = (
                dt.datetime.fromtimestamp(publish_ts).date().isoformat() if publish_ts else "N/A"
            )
            link = item.get("link", "")
            if not isinstance(link, str):
                link = ""
            link = link.strip()
            if not link:
                link = f"https://finance.yahoo.com/quote/{symbol}/news"
            result.append(
                {
                    "title": item.get("title", "Yahoo Finance News"),
                    "summary": item.get("summary", "")[:220],
                    "url": link,
                    "published_at": published_at,
                }
            )
        return result

    def build_event_signal(
        self,
        question: str,
        event_date: dt.date,
        event_snapshot: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if not event_snapshot:
            return None

        query_date = event_snapshot.get("event_query_date", event_date.isoformat())
        if not event_snapshot.get("event_has_data"):
            previous_date = event_snapshot.get("event_prev_trade_date")
            next_date = event_snapshot.get("event_next_trade_date")
            neighbor_text_parts: List[str] = []
            if previous_date:
                neighbor_text_parts.append(f"前一交易日 {previous_date}")
            if next_date:
                neighbor_text_parts.append(f"后一交易日 {next_date}")
            neighbor_text = f"（可参考{'，'.join(neighbor_text_parts)}）" if neighbor_text_parts else ""
            return f"事件日核验：{query_date} 非交易日或无数据{neighbor_text}。"

        trade_date = event_snapshot.get("event_trade_date", query_date)
        event_change = event_snapshot.get("event_change_pct")
        if event_change is None:
            return f"事件日核验：{trade_date} 数据不完整，无法计算相对前一交易日涨跌。"

        direction = "上涨" if event_change >= 0 else "下跌"
        magnitude = abs(float(event_change))
        message = f"事件日核验：{trade_date} 收盘较前一交易日{direction} {magnitude:.2f}%。"
        threshold = normalize_large_move_threshold(
            event_snapshot.get("event_big_move_threshold_pct") if event_snapshot else None,
            default=self.large_move_threshold_pct,
        )
        if is_large_move_question(question):
            if is_large_move(magnitude, threshold):
                message += f" 该幅度已达到常见“明显大幅波动”（约≥{threshold:.1f}%）阈值。"
            else:
                message += f" 该幅度未达到常见“大涨/大跌”（约≥{threshold:.1f}%）阈值，更接近小幅波动。"
        return message

    def find_news_near_event(
        self,
        news_items: List[Dict[str, Any]],
        event_date: dt.date,
        used_titles: set[str],
        max_day_gap: int = 2,
    ) -> Optional[Dict[str, Any]]:
        candidates: List[tuple[int, Dict[str, Any]]] = []
        for item in news_items:
            title = item.get("title")
            if not title or title in used_titles:
                continue
            published_at = item.get("published_at")
            if not isinstance(published_at, str):
                continue
            try:
                published_date = dt.date.fromisoformat(published_at)
            except Exception:
                continue
            gap = abs((published_date - event_date).days)
            if gap <= max_day_gap:
                candidates.append((gap, item))
        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]

    def build_earnings_signal(
        self, news_items: List[Dict[str, Any]], ticker: Optional[yf.Ticker], used_titles: set[str]
    ) -> str:
        earnings_keywords = [
            "earnings",
            "guidance",
            "eps",
            "revenue",
            "profit",
            "quarter",
            "q1",
            "q2",
            "q3",
            "q4",
            "财报",
            "业绩",
            "季度",
            "指引",
            "净利润",
            "营收",
        ]
        matched = self._find_news_by_keywords(news_items, earnings_keywords, used_titles)
        if matched:
            used_titles.add(matched["title"])
            return f"财报线索：{self.format_news_brief(matched)}。"

        earnings_date = self._extract_recent_earnings_date(ticker)
        if earnings_date:
            return f"财报线索：最近可识别财报节点在 {earnings_date}，需结合业绩与业绩指引判断基本面驱动。"
        return "财报线索：当前新闻未出现明确财报关键词，财报驱动证据有限。"

    def build_macro_signal(self, news_items: List[Dict[str, Any]], used_titles: set[str]) -> str:
        macro_keywords = [
            "fed",
            "fomc",
            "interest rate",
            "inflation",
            "cpi",
            "pce",
            "yield",
            "treasury",
            "gdp",
            "tariff",
            "usd",
            "dollar",
            "recession",
            "macro",
            "美联储",
            "加息",
            "降息",
            "利率",
            "通胀",
            "关税",
            "国债收益率",
            "宏观",
        ]
        matched = self._find_news_by_keywords(news_items, macro_keywords, used_titles)
        if matched:
            used_titles.add(matched["title"])
            return f"宏观线索：{self.format_news_brief(matched)}。"
        return "宏观线索：当前新闻未出现明显利率/通胀/政策关键词，宏观变量影响暂未形成强证据。"

    def build_company_news_signal(
        self, news_items: List[Dict[str, Any]], used_titles: set[str]
    ) -> Optional[str]:
        remaining = [item for item in news_items if item.get("title") and item["title"] not in used_titles]
        if not remaining:
            return None
        picks = remaining[:2]
        for item in picks:
            used_titles.add(item["title"])
        joined = "；".join([self.format_news_brief(item) for item in picks])
        return f"新闻线索：{joined}。"

    def estimate_confidence(
        self,
        data_provider: str,
        news_items: List[Dict[str, Any]],
        event_snapshot: Optional[Dict[str, Any]],
    ) -> float:
        if data_provider == "yahoo":
            score = 0.78
        elif data_provider == "eastmoney":
            score = 0.74
        elif data_provider == "stooq":
            score = 0.68
        else:
            score = 0.55

        if len(news_items) >= 3:
            score += 0.05
        elif len(news_items) == 0:
            score -= 0.03

        if event_snapshot:
            if event_snapshot.get("event_has_data"):
                score += 0.05
            else:
                score -= 0.05

        score = max(0.45, min(0.95, score))
        return round(score, 2)

    def format_news_brief(self, item: Dict[str, Any]) -> str:
        title = item.get("title", "相关新闻")
        published_at = item.get("published_at", "N/A")
        return f"{title}（{published_at}）"

    def _find_news_by_keywords(
        self, news_items: List[Dict[str, Any]], keywords: List[str], used_titles: set[str]
    ) -> Optional[Dict[str, Any]]:
        normalized_keywords = [keyword.lower() for keyword in keywords]
        for item in news_items:
            title = item.get("title", "")
            if not title or title in used_titles:
                continue
            text = f"{title} {item.get('summary', '')}".lower()
            if any(keyword in text for keyword in normalized_keywords):
                return item
        return None

    def _extract_recent_earnings_date(self, ticker: Optional[yf.Ticker]) -> Optional[str]:
        if ticker is None:
            return None
        try:
            earnings_df = ticker.get_earnings_dates(limit=2)
            if earnings_df is None or earnings_df.empty:
                return None
            first_index = earnings_df.index[0]
            return pd.to_datetime(first_index).date().isoformat()
        except Exception:
            return None
