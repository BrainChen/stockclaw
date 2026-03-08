import datetime as dt
import re
from time import sleep
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from app.core.config import get_settings
from app.common.market_rules import is_large_move, is_large_move_question, normalize_large_move_threshold
from app.services.symbol_resolver_service import SymbolResolverService
from app.common.symbol_utils import is_a_share_symbol, to_eastmoney_secid, to_stooq_symbol


@dataclass
class MarketAnalysis:
    symbol: str
    objective_data: Dict[str, Any]
    analysis: List[str]
    sources: List[Dict[str, Any]]


class MarketService:
    def __init__(self) -> None:
        self.symbol_resolver = SymbolResolverService()
        self.settings = get_settings()
        self._headers = {"User-Agent": "Mozilla/5.0"}
        self._eastmoney_session = requests.Session()
        self._eastmoney_session.trust_env = False
        self.large_move_threshold_pct = normalize_large_move_threshold(
            self.settings.event_large_move_threshold_pct,
            default=3.0,
        )

    def analyze(self, question: str, symbol: Optional[str]) -> MarketAnalysis:
        resolved_symbol = symbol or self.symbol_resolver.resolve(question)
        if not resolved_symbol:
            raise ValueError("未识别到股票代码，请补充更明确的公司名称或交易代码（如 BABA、1810.HK、600519.SS）。")

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
        change_14d = self._calc_change(closes, days=14)
        change_30d = self._calc_change(closes, days=30)
        trend = self._classify_trend(closes.tail(14))
        volatility_14d = self._calc_volatility(closes.tail(14))
        requested_window_days = self._extract_requested_days(question)
        requested_change = (
            self._calc_change(closes, days=requested_window_days) if requested_window_days else None
        )
        event_date = self._extract_date_from_question(question)
        event_snapshot = self._build_event_snapshot(history, event_date) if event_date else None
        chart_window_days = requested_window_days or 30
        price_series = self._build_price_series(closes=closes, window_days=chart_window_days)
        volume_series = self._build_volume_series(history=history, window_days=chart_window_days)
        actual_chart_window_days = len(price_series)

        news_items = self._fetch_news(ticker, resolved_symbol) if ticker is not None else []
        currency = self._safe_currency(ticker, resolved_symbol, data_provider)
        confidence = self._estimate_confidence(
            data_provider=data_provider,
            news_items=news_items,
            event_snapshot=event_snapshot,
        )

        objective_data = {
            "latest_close": round(latest_close, 4),
            "latest_date": latest_date.isoformat(),
            "data_as_of": latest_date.isoformat(),
            "analysis_generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "currency": currency,
            "data_provider": data_provider,
            "fallback_used": data_provider == "stooq",
            "change_7d_pct": round(change_7d, 2),
            "change_14d_pct": round(change_14d, 2),
            "change_30d_pct": round(change_30d, 2),
            "trend_14d": trend,
            "volatility_14d_pct": round(volatility_14d, 2),
            "analysis_confidence": confidence,
            "news_count": len(news_items) if ticker is not None else 0,
            "chart_window_days": actual_chart_window_days,
            "price_series": price_series,
            "volume_series": volume_series,
        }
        if requested_window_days is not None and requested_change is not None:
            objective_data["requested_window_days"] = requested_window_days
            objective_data["requested_change_pct"] = round(requested_change, 2)
        if event_snapshot:
            objective_data.update(event_snapshot)

        analysis = self._build_analysis(
            question=question,
            history=history,
            closes=closes,
            trend=trend,
            news_items=news_items,
            event_date=event_date,
            event_snapshot=event_snapshot,
            change_14d=change_14d,
            volatility_14d=volatility_14d,
            ticker=ticker,
        )

        sources = [self._build_market_source(resolved_symbol, data_provider)]
        for news in news_items[:5]:
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
        is_a_share = is_a_share_symbol(symbol)

        max_attempts = max(1, int(self.settings.external_api_max_attempts))
        retry_delay_seconds = max(0.2, float(self.settings.external_api_backoff_ms) / 1000)
        for _ in range(max_attempts):
            try:
                history = ticker.history(period="3mo", interval="1d", auto_adjust=False)
                if not history.empty:
                    return history, "yahoo", ticker
            except Exception:
                sleep(retry_delay_seconds)

        if is_a_share:
            eastmoney_history = self._fetch_history_eastmoney(symbol)
            if not eastmoney_history.empty:
                return eastmoney_history, "eastmoney", None

        stooq_history = self._fetch_history_stooq(symbol)
        if not stooq_history.empty:
            return stooq_history, "stooq", None

        return pd.DataFrame(), "none", None

    def _fetch_history_eastmoney(self, symbol: str) -> pd.DataFrame:
        secid = to_eastmoney_secid(symbol)
        if not secid:
            return pd.DataFrame()
        payload = None
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "klt": "101",
            "fqt": "1",
            "lmt": "120",
            "end": "20500101",
        }
        max_attempts = max(1, int(self.settings.external_api_max_attempts))
        retry_delay_seconds = max(0.2, float(self.settings.external_api_backoff_ms) / 1000)
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._eastmoney_session.get(
                    "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                    params=params,
                    headers=self._headers,
                    timeout=8.0,
                )
                if response.status_code == 200:
                    parsed = response.json()
                    if isinstance(parsed, dict):
                        payload = parsed
                        break
            except Exception:
                pass
            if attempt < max_attempts:
                sleep(retry_delay_seconds)
        if payload is None:
            return pd.DataFrame()

        data = payload.get("data", {}) or {}
        klines = data.get("klines", []) or []
        if not klines:
            return pd.DataFrame()

        rows: List[Dict[str, Any]] = []
        for line in klines:
            if not isinstance(line, str):
                continue
            parts = line.split(",")
            if len(parts) < 6:
                continue
            rows.append(
                {
                    "Date": parts[0],
                    "Open": parts[1],
                    "Close": parts[2],
                    "High": parts[3],
                    "Low": parts[4],
                    "Volume": parts[5],
                }
            )
        if not rows:
            return pd.DataFrame()

        frame = pd.DataFrame(rows)
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["Date", "Close"]).sort_values("Date")
        if frame.empty:
            return pd.DataFrame()
        return frame.set_index("Date").tail(90)

    def _fetch_history_stooq(self, symbol: str) -> pd.DataFrame:
        stooq_symbol = to_stooq_symbol(symbol)
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

    def _fetch_news(self, ticker: yf.Ticker, symbol: str) -> List[Dict[str, Any]]:
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

    def _safe_currency(
        self, ticker: Optional[yf.Ticker], symbol: str, data_provider: str
    ) -> str:
        if data_provider == "eastmoney":
            return "CNY"
        if data_provider == "stooq":
            if symbol.endswith(".HK"):
                return "HKD"
            if symbol.endswith((".SS", ".SZ")):
                return "CNY"
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
        if data_provider == "eastmoney":
            normalized_symbol = symbol.upper()
            if normalized_symbol.endswith(".SS"):
                em_path = f"sh{normalized_symbol.split('.')[0]}"
            elif normalized_symbol.endswith(".SZ"):
                em_path = f"sz{normalized_symbol.split('.')[0]}"
            else:
                em_path = normalized_symbol
            return {
                "source_type": "market",
                "title": f"{symbol} - Eastmoney Market Data (A-share Fallback)",
                "content": "OHLCV daily history from Eastmoney push2his API",
                "url": f"https://quote.eastmoney.com/{em_path}.html",
                "score": None,
            }
        if data_provider == "stooq":
            return {
                "source_type": "market",
                "title": f"{symbol} - Stooq Market Data (Fallback)",
                "content": "OHLCV daily history from Stooq as fallback provider",
                "url": f"https://stooq.com/q/?s={to_stooq_symbol(symbol)}",
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
            "url": f"https://finance.yahoo.com/quote/{symbol}",
            "score": None,
        }

    def _extract_date_from_question(self, question: str) -> Optional[dt.date]:
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

    def _build_event_snapshot(
        self, history: pd.DataFrame, event_date: dt.date
    ) -> Dict[str, Any]:
        frame = history.copy()
        frame.index = pd.to_datetime(frame.index).date
        trade_dates = list(frame.index)
        snapshot: Dict[str, Any] = {
            "event_query_date": event_date.isoformat(),
            "event_big_move_threshold_pct": self.large_move_threshold_pct,
        }

        if event_date not in frame.index:
            snapshot["event_has_data"] = False
            previous_dates = [date_value for date_value in trade_dates if date_value < event_date]
            next_dates = [date_value for date_value in trade_dates if date_value > event_date]
            if previous_dates:
                snapshot["event_prev_trade_date"] = previous_dates[-1].isoformat()
            if next_dates:
                snapshot["event_next_trade_date"] = next_dates[0].isoformat()
            return snapshot

        event_idx = trade_dates.index(event_date)
        event_row = frame.iloc[event_idx]

        event_close = self._safe_number(event_row.get("Close"))
        event_open = self._safe_number(event_row.get("Open"))
        event_high = self._safe_number(event_row.get("High"))
        event_low = self._safe_number(event_row.get("Low"))
        event_volume = self._safe_number(event_row.get("Volume"))
        prev_close = self._safe_number(frame.iloc[event_idx - 1].get("Close")) if event_idx > 0 else None

        snapshot["event_has_data"] = True
        snapshot["event_trade_date"] = event_date.isoformat()
        if event_close is not None:
            snapshot["event_close"] = round(event_close, 4)
        if event_open is not None:
            snapshot["event_open"] = round(event_open, 4)
        if event_high is not None:
            snapshot["event_high"] = round(event_high, 4)
        if event_low is not None:
            snapshot["event_low"] = round(event_low, 4)
        if event_volume is not None:
            snapshot["event_volume"] = round(event_volume, 2)
        if prev_close is not None and prev_close != 0 and event_close is not None:
            event_change_pct = (event_close - prev_close) / prev_close * 100
            snapshot["event_prev_close"] = round(prev_close, 4)
            snapshot["event_change_pct"] = round(event_change_pct, 2)
            snapshot["event_is_large_move"] = is_large_move(
                change_pct=event_change_pct,
                threshold_pct=self.large_move_threshold_pct,
            )
        if event_open is not None and event_open != 0 and event_close is not None:
            intraday_change_pct = (event_close - event_open) / event_open * 100
            snapshot["event_intraday_change_pct"] = round(intraday_change_pct, 2)
        return snapshot

    def _safe_number(self, value: Any) -> Optional[float]:
        numeric = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric):
            return None
        return float(numeric)

    def _extract_requested_days(self, question: str) -> Optional[int]:
        normalized = question.replace("个交易日", "天").replace("交易日", "天").replace(" 日", "天")
        match = re.search(r"(?:最近|近)?\s*(\d{1,3})\s*天", normalized)
        if not match:
            return None
        days = int(match.group(1))
        if days <= 0 or days > 120:
            return None
        return days

    def _build_price_series(self, closes: pd.Series, window_days: int) -> List[Dict[str, Any]]:
        if closes.empty:
            return []
        window_days = max(2, min(int(window_days), len(closes)))
        window = closes.tail(window_days)
        series: List[Dict[str, Any]] = []
        for ts, close_value in window.items():
            trade_date = ts.date().isoformat() if hasattr(ts, "date") else pd.to_datetime(ts).date().isoformat()
            series.append({"date": trade_date, "close": round(float(close_value), 4)})
        return series

    def _build_volume_series(self, history: pd.DataFrame, window_days: int) -> List[Dict[str, Any]]:
        if "Volume" not in history.columns:
            return []
        frame = history.copy()
        frame["Volume"] = pd.to_numeric(frame["Volume"], errors="coerce")
        frame = frame.dropna(subset=["Volume"])
        if frame.empty:
            return []
        window_days = max(2, min(int(window_days), len(frame)))
        frame = frame.tail(window_days)
        series: List[Dict[str, Any]] = []
        for ts, row in frame.iterrows():
            trade_date = ts.date().isoformat() if hasattr(ts, "date") else pd.to_datetime(ts).date().isoformat()
            series.append({"date": trade_date, "volume": round(float(row["Volume"]), 2)})
        return series

    def _build_analysis(
        self,
        question: str,
        history: pd.DataFrame,
        closes: pd.Series,
        trend: str,
        news_items: List[Dict[str, Any]],
        event_date: Optional[dt.date],
        event_snapshot: Optional[Dict[str, Any]],
        change_14d: float,
        volatility_14d: float,
        ticker: Optional[yf.Ticker],
    ) -> List[str]:
        analysis = [
            f"价格结构：近14个交易日累计涨跌 {change_14d:.2f}%，形态为{trend}，14日年化波动率约 {volatility_14d:.2f}%。"
        ]
        used_titles: set[str] = set()

        if event_date:
            event_signal = self._build_event_signal(
                question=question, event_date=event_date, event_snapshot=event_snapshot
            )
            if event_signal:
                analysis.append(event_signal)

            related_news = self._find_news_near_event(
                news_items=news_items,
                event_date=event_date,
                used_titles=used_titles,
                max_day_gap=2,
            )
            if related_news:
                used_titles.add(related_news["title"])
                analysis.append(f"事件窗口新闻：{self._format_news_brief(related_news)}。")
            else:
                analysis.append("事件窗口新闻：未检索到事件日前后2日的明确公司新闻，证据不足。")
        else:
            top_move_desc = self._find_largest_daily_move(closes.tail(30))
            if top_move_desc:
                analysis.append(top_move_desc)

        volume_signal = self._build_volume_signal(history)
        if volume_signal:
            analysis.append(volume_signal)

        earnings_signal = self._build_earnings_signal(news_items, ticker, used_titles)
        analysis.append(earnings_signal)

        macro_signal = self._build_macro_signal(news_items, used_titles)
        analysis.append(macro_signal)

        company_news_signal = self._build_company_news_signal(news_items, used_titles)
        if company_news_signal:
            analysis.append(company_news_signal)

        if "为何" in question or "为什么" in question:
            analysis.append("原因分析基于公开新闻与价格共振，仅代表归因线索，不构成投资建议。")
        return analysis[:7]

    def _build_event_signal(
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

    def _find_news_near_event(
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

    def _find_largest_daily_move(self, closes_30d: pd.Series) -> Optional[str]:
        if len(closes_30d) < 3:
            return None
        returns = closes_30d.pct_change().dropna()
        if returns.empty:
            return None
        max_idx = returns.abs().idxmax()
        max_val = float(returns.loc[max_idx] * 100)
        return f"近 30 日单日最大波动出现在 {max_idx.date().isoformat()}，幅度 {max_val:.2f}%。"

    def _build_volume_signal(self, history: pd.DataFrame) -> Optional[str]:
        if "Volume" not in history.columns:
            return None
        volumes = pd.to_numeric(history["Volume"], errors="coerce").dropna()
        if len(volumes) < 20:
            return None
        avg_5d = float(volumes.tail(5).mean())
        avg_20d = float(volumes.tail(20).mean())
        if avg_20d <= 0:
            return None
        ratio_pct = (avg_5d / avg_20d - 1) * 100
        if ratio_pct >= 10:
            return f"量价结构：近5日成交量较近20日均量放大 {ratio_pct:.2f}%，交易活跃度上升。"
        if ratio_pct <= -10:
            return f"量价结构：近5日成交量较近20日均量回落 {abs(ratio_pct):.2f}%，短线资金活跃度下降。"
        return f"量价结构：近5日成交量与近20日均量接近（变化 {ratio_pct:.2f}%），量能未出现显著异动。"

    def _build_earnings_signal(
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
            return f"财报线索：{self._format_news_brief(matched)}。"

        earnings_date = self._extract_recent_earnings_date(ticker)
        if earnings_date:
            return f"财报线索：最近可识别财报节点在 {earnings_date}，需结合业绩与业绩指引判断基本面驱动。"
        return "财报线索：当前新闻未出现明确财报关键词，财报驱动证据有限。"

    def _build_macro_signal(self, news_items: List[Dict[str, Any]], used_titles: set[str]) -> str:
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
            return f"宏观线索：{self._format_news_brief(matched)}。"
        return "宏观线索：当前新闻未出现明显利率/通胀/政策关键词，宏观变量影响暂未形成强证据。"

    def _build_company_news_signal(
        self, news_items: List[Dict[str, Any]], used_titles: set[str]
    ) -> Optional[str]:
        remaining = [item for item in news_items if item.get("title") and item["title"] not in used_titles]
        if not remaining:
            return None
        picks = remaining[:2]
        for item in picks:
            used_titles.add(item["title"])
        joined = "；".join([self._format_news_brief(item) for item in picks])
        return f"新闻线索：{joined}。"

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

    def _format_news_brief(self, item: Dict[str, Any]) -> str:
        title = item.get("title", "相关新闻")
        published_at = item.get("published_at", "N/A")
        return f"{title}（{published_at}）"

    def _estimate_confidence(
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
