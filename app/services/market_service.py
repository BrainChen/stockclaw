import datetime as dt
import re
from time import sleep
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import numpy as np
import pandas as pd
import yfinance as yf

from app.services.symbol_resolver_service import SymbolResolverService


@dataclass
class MarketAnalysis:
    symbol: str
    objective_data: Dict[str, Any]
    analysis: List[str]
    sources: List[Dict[str, Any]]


class MarketService:
    def __init__(self) -> None:
        self.symbol_resolver = SymbolResolverService()

    def analyze(self, question: str, symbol: Optional[str]) -> MarketAnalysis:
        resolved_symbol = symbol or self.symbol_resolver.resolve(question)
        if not resolved_symbol:
            raise ValueError("未识别到股票代码，请补充更明确的公司名称或交易代码（如 BABA、1810.HK）。")

        history, data_provider, ticker = self._fetch_history_with_fallback(resolved_symbol)
        if history.empty:
            raise ValueError(
                f"未获取到 {resolved_symbol} 的行情数据。可能因为上游行情源限流或代码不可用，请稍后重试。"
            )

        history = history.dropna(subset=["Close"])
        if history.empty:
            raise ValueError(f"{resolved_symbol} 行情数据为空。")
        closes = history["Close"]
        latest_index = closes.index[-1]
        latest_date = latest_index.date() if hasattr(latest_index, "date") else pd.to_datetime(latest_index).date()
        latest_close = float(closes.iloc[-1])

        change_7d = self._calc_change(closes, days=7)
        change_30d = self._calc_change(closes, days=30)
        trend = self._classify_trend(closes.tail(14))
        volatility_14d = self._calc_volatility(closes.tail(14))

        currency = self._safe_currency(ticker, resolved_symbol, data_provider)

        objective_data = {
            "latest_close": round(latest_close, 4),
            "latest_date": latest_date.isoformat(),
            "currency": currency,
            "change_7d_pct": round(change_7d, 2),
            "change_30d_pct": round(change_30d, 2),
            "trend_14d": trend,
            "volatility_14d_pct": round(volatility_14d, 2),
        }

        news_items = self._fetch_news(ticker) if ticker is not None else []
        event_date = self._extract_date_from_question(question)
        analysis = self._build_analysis(question, closes, trend, news_items, event_date)

        sources = [self._build_market_source(resolved_symbol, data_provider)]
        for news in news_items[:3]:
            sources.append(
                {
                    "source_type": "market",
                    "title": news["title"],
                    "content": news["summary"],
                    "url": news["url"],
                    "score": None,
                }
            )

        return MarketAnalysis(
            symbol=resolved_symbol,
            objective_data=objective_data,
            analysis=analysis,
            sources=sources,
        )

    def _fetch_history_with_fallback(
        self, symbol: str
    ) -> tuple[pd.DataFrame, str, Optional[yf.Ticker]]:
        ticker = yf.Ticker(symbol)

        for _ in range(2):
            try:
                history = ticker.history(period="3mo", interval="1d", auto_adjust=False)
                if not history.empty:
                    return history, "yahoo", ticker
            except Exception:
                sleep(0.6)

        stooq_history = self._fetch_history_stooq(symbol)
        if not stooq_history.empty:
            return stooq_history, "stooq", None

        return pd.DataFrame(), "none", None

    def _fetch_history_stooq(self, symbol: str) -> pd.DataFrame:
        stooq_symbol = self._to_stooq_symbol(symbol)
        url = f"https://stooq.com/q/d/l/?s={quote(stooq_symbol)}&i=d"
        try:
            frame = pd.read_csv(url)
            if frame.empty or "Close" not in frame.columns:
                return pd.DataFrame()
            frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
            frame = frame.dropna(subset=["Date", "Close"]).sort_values("Date")
            if frame.empty:
                return pd.DataFrame()
            frame = frame.set_index("Date")
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                if col in frame.columns:
                    frame[col] = pd.to_numeric(frame[col], errors="coerce")
            frame = frame.dropna(subset=["Close"])
            return frame.tail(90)
        except Exception:
            return pd.DataFrame()

    def _to_stooq_symbol(self, symbol: str) -> str:
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

    def _calc_change(self, closes: pd.Series, days: int) -> float:
        if len(closes) < 2:
            return 0.0
        start_idx = max(0, len(closes) - days - 1)
        start_val = float(closes.iloc[start_idx])
        end_val = float(closes.iloc[-1])
        if start_val == 0:
            return 0.0
        return (end_val - start_val) / start_val * 100

    def _classify_trend(self, closes_14d: pd.Series) -> str:
        if len(closes_14d) < 2:
            return "数据不足"
        start_val = float(closes_14d.iloc[0])
        end_val = float(closes_14d.iloc[-1])
        pct_change = (end_val - start_val) / start_val * 100 if start_val else 0.0
        if pct_change >= 3:
            return "上涨"
        if pct_change <= -3:
            return "下跌"
        return "震荡"

    def _calc_volatility(self, closes_14d: pd.Series) -> float:
        if len(closes_14d) < 3:
            return 0.0
        daily_returns = closes_14d.pct_change().dropna()
        return float(np.std(daily_returns) * np.sqrt(252) * 100)

    def _fetch_news(self, ticker: yf.Ticker) -> List[Dict[str, Any]]:
        try:
            raw_news = getattr(ticker, "news", []) or []
        except Exception:
            raw_news = []
        result = []
        for item in raw_news[:10]:
            publish_ts = item.get("providerPublishTime")
            published_at = (
                dt.datetime.fromtimestamp(publish_ts).date().isoformat() if publish_ts else "N/A"
            )
            result.append(
                {
                    "title": item.get("title", "Yahoo Finance News"),
                    "summary": item.get("summary", "")[:220],
                    "url": item.get("link", ""),
                    "published_at": published_at,
                }
            )
        return result

    def _safe_currency(
        self, ticker: Optional[yf.Ticker], symbol: str, data_provider: str
    ) -> str:
        if data_provider == "stooq":
            if symbol.endswith(".HK"):
                return "HKD"
            if symbol.endswith(".US") or symbol.isalpha():
                return "USD"
            return "N/A"
        if ticker is None:
            return "N/A"
        try:
            info = ticker.info or {}
            return info.get("currency", "N/A")
        except Exception:
            return "N/A"

    def _build_market_source(self, symbol: str, data_provider: str) -> Dict[str, Any]:
        if data_provider == "stooq":
            return {
                "source_type": "market",
                "title": f"{symbol} - Stooq Market Data (Fallback)",
                "content": "OHLCV daily history from Stooq as fallback provider",
                "url": f"https://stooq.com/q/?s={self._to_stooq_symbol(symbol)}",
                "score": None,
            }
        if data_provider == "yahoo":
            return {
                "source_type": "market",
                "title": f"{symbol} - Yahoo Finance Market Data",
                "content": "OHLCV daily history from Yahoo Finance",
                "url": f"https://finance.yahoo.com/quote/{symbol}",
                "score": None,
            }
        return {
            "source_type": "market",
            "title": f"{symbol} - Market Data",
            "content": "No provider available",
            "url": None,
            "score": None,
        }

    def _extract_date_from_question(self, question: str) -> Optional[dt.date]:
        match = re.search(r"(\d{1,2})月(\d{1,2})日", question)
        if not match:
            return None
        month = int(match.group(1))
        day = int(match.group(2))
        year = dt.date.today().year
        try:
            candidate = dt.date(year, month, day)
            if candidate > dt.date.today():
                candidate = dt.date(year - 1, month, day)
            return candidate
        except ValueError:
            return None

    def _build_analysis(
        self,
        question: str,
        closes: pd.Series,
        trend: str,
        news_items: List[Dict[str, Any]],
        event_date: Optional[dt.date],
    ) -> List[str]:
        analysis = [f"近 14 个交易日价格形态为：{trend}。"]

        if event_date:
            movement_desc = self._get_event_movement(closes, event_date)
            if movement_desc:
                analysis.append(movement_desc)
            related_news = [item for item in news_items if item["published_at"] == event_date.isoformat()]
            if related_news:
                analysis.append(f"事件日附近新闻：{related_news[0]['title']}")
        else:
            top_move_desc = self._find_largest_daily_move(closes.tail(30))
            if top_move_desc:
                analysis.append(top_move_desc)
            if news_items:
                analysis.append(f"近期可能影响因素：{news_items[0]['title']}")

        if "为何" in question or "为什么" in question:
            analysis.append("原因分析基于公开新闻与价格共振，仅代表归因线索，不构成投资建议。")
        return analysis

    def _get_event_movement(self, closes: pd.Series, event_date: dt.date) -> Optional[str]:
        series = closes.copy()
        series.index = pd.to_datetime(series.index).date
        if event_date not in series.index:
            return f"{event_date.isoformat()} 非交易日或无数据。"
        idx = list(series.index).index(event_date)
        if idx == 0:
            return None
        prev_close = float(series.iloc[idx - 1])
        event_close = float(series.iloc[idx])
        if prev_close == 0:
            return None
        change = (event_close - prev_close) / prev_close * 100
        direction = "上涨" if change >= 0 else "下跌"
        return f"{event_date.isoformat()} 当日收盘较前一交易日{direction} {abs(change):.2f}%。"

    def _find_largest_daily_move(self, closes_30d: pd.Series) -> Optional[str]:
        if len(closes_30d) < 3:
            return None
        returns = closes_30d.pct_change().dropna()
        if returns.empty:
            return None
        max_idx = returns.abs().idxmax()
        max_val = float(returns.loc[max_idx] * 100)
        return f"近 30 日单日最大波动出现在 {max_idx.date().isoformat()}，幅度 {max_val:.2f}%。"
