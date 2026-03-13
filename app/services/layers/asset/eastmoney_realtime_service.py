import datetime as dt
import re
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from app.common.logger import get_logger, kv


MarketType = Literal["cn_a", "hk", "us"]
MarketPhase = Literal["pre_market", "intraday", "post_market", "closed"]


class EastmoneyRealtimeService:
    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self._headers = {"User-Agent": "Mozilla/5.0"}
        self._session = requests.Session()
        self._session.trust_env = False
        self._suggest_token = "D43BF722C8E33BDC906FB84D85E326E8"
        self._snapshot_url = "https://push2.eastmoney.com/api/qt/stock/get"
        self._trends_url = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"

    def fetch_realtime(
        self,
        quote_url: str,
        ndays: int = 1,
        max_points: int = 240,
    ) -> Dict[str, Any]:
        parsed = self._parse_quote_url(quote_url)
        secid = self._resolve_secid(parsed)
        snapshot, snapshot_resource_url = self._fetch_snapshot(secid=secid)
        trend_points, trends_resource_url = self._fetch_trends(
            secid=secid,
            ndays=ndays,
            max_points=max_points,
        )
        phase_info = self._resolve_market_phase(parsed["market"])
        session_analysis = self._build_session_analysis(
            phase=phase_info["phase"],
            snapshot=snapshot,
            trend_points=trend_points,
        )
        session_points = self._build_session_points(snapshot=snapshot, trend_points=trend_points)

        self.logger.info(
            "eastmoney realtime fetched %s",
            kv(
                symbol=parsed["symbol"],
                market=parsed["market"],
                secid=secid,
                phase=phase_info["phase"],
                trend_points=len(trend_points),
            ),
        )
        return {
            "quote_url": parsed["normalized_url"],
            "market": parsed["market"],
            "symbol": parsed["symbol"],
            "secid": secid,
            "exchange_timezone": phase_info["timezone"],
            "phase": phase_info["phase"],
            "phase_checked_at": phase_info["checked_at"],
            "snapshot": snapshot,
            "session_analysis": session_analysis,
            "session_points": session_points,
            "trend_points_count": len(trend_points),
            "resource_urls": [
                parsed["normalized_url"],
                snapshot_resource_url,
                trends_resource_url,
            ],
        }

    def _parse_quote_url(self, quote_url: str) -> Dict[str, str]:
        raw = quote_url.strip()
        if not raw:
            raise ValueError("Eastmoney 页面链接不能为空。")
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("仅支持 http/https 的 Eastmoney 页面链接。")
        host = parsed.netloc.lower()
        if "quote.eastmoney.com" not in host:
            raise ValueError("仅支持 quote.eastmoney.com 域名。")

        path = (parsed.path or "").strip()
        normalized_url = f"{parsed.scheme}://{parsed.netloc}{path}"

        a_share_match = re.fullmatch(r"/(sh|sz)(\d{6})\.html", path, flags=re.IGNORECASE)
        if a_share_match:
            board = a_share_match.group(1).lower()
            symbol = a_share_match.group(2)
            return {
                "market": "cn_a",
                "board": board,
                "symbol": symbol,
                "normalized_url": normalized_url,
            }

        hk_match = re.fullmatch(r"/hk/(\d{4,5})\.html", path, flags=re.IGNORECASE)
        if hk_match:
            symbol = hk_match.group(1).zfill(5)
            return {
                "market": "hk",
                "board": "hk",
                "symbol": symbol,
                "normalized_url": normalized_url,
            }

        us_match = re.fullmatch(r"/us/([A-Za-z][A-Za-z0-9\.\-]{0,9})\.html", path, flags=re.IGNORECASE)
        if us_match:
            symbol = us_match.group(1).upper()
            return {
                "market": "us",
                "board": "us",
                "symbol": symbol,
                "normalized_url": normalized_url,
            }

        raise ValueError("暂不支持该 Eastmoney 页面路径。请使用 sh/sz、hk、us 个股链接。")

    def _resolve_secid(self, parsed: Dict[str, str]) -> str:
        market = parsed["market"]
        symbol = parsed["symbol"]
        if market == "cn_a":
            board = parsed["board"]
            if board == "sh":
                return f"1.{symbol}"
            return f"0.{symbol}"
        if market == "hk":
            return f"116.{symbol}"
        return self._resolve_us_secid(symbol)

    def _resolve_us_secid(self, symbol: str) -> str:
        suggest_params = {
            "input": symbol,
            "type": "14",
            "count": "20",
            "token": self._suggest_token,
        }
        try:
            response = self._session.get(
                "https://searchapi.eastmoney.com/api/suggest/get",
                params=suggest_params,
                headers=self._headers,
                timeout=8.0,
            )
            payload = response.json() if response.status_code == 200 else {}
        except Exception:
            payload = {}
        rows = payload.get("QuotationCodeTable", {}).get("Data", []) if isinstance(payload, dict) else []
        exact_quote_id: Optional[str] = None
        fallback_quote_id: Optional[str] = None
        for item in rows:
            if str(item.get("Classify", "") or "") != "UsStock":
                continue
            quote_id = str(item.get("QuoteID", "") or "")
            if not quote_id:
                continue
            code = str(item.get("Code", "") or "").upper()
            if code == symbol:
                exact_quote_id = quote_id
                break
            if fallback_quote_id is None:
                fallback_quote_id = quote_id
        if exact_quote_id:
            return exact_quote_id
        if fallback_quote_id:
            return fallback_quote_id

        for market_prefix in ["105", "106", "107"]:
            candidate = f"{market_prefix}.{symbol}"
            if self._validate_secid(candidate):
                return candidate
        raise ValueError(f"未能解析美股 {symbol} 的 secid。")

    def _validate_secid(self, secid: str) -> bool:
        params = {
            "secid": secid,
            "fields": "f57,f58,f43",
        }
        try:
            response = self._session.get(
                self._snapshot_url,
                params=params,
                headers=self._headers,
                timeout=6.0,
            )
            payload = response.json() if response.status_code == 200 else {}
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("rc") != 0:
            return False
        data = payload.get("data") or {}
        return bool(data.get("f57"))

    def _fetch_snapshot(self, secid: str) -> tuple[Dict[str, Any], str]:
        params = {
            "secid": secid,
            "fields": "f57,f58,f59,f43,f46,f44,f45,f60,f47,f48,f50,f168,f169,f170,f171,f86,f292",
        }
        response = self._session.get(
            self._snapshot_url,
            params=params,
            headers=self._headers,
            timeout=8.0,
        )
        payload = response.json() if response.status_code == 200 else {}
        if not isinstance(payload, dict) or payload.get("rc") != 0:
            raise ValueError(f"Eastmoney 实时快照拉取失败，secid={secid}")
        data = payload.get("data") or {}
        if not data:
            raise ValueError(f"Eastmoney 实时快照为空，secid={secid}")

        price_precision = self._safe_int(data.get("f59"), default=2)
        snapshot = {
            "name": str(data.get("f58", "") or ""),
            "code": str(data.get("f57", "") or ""),
            "price_precision": price_precision,
            "latest_price": self._scale_price(data.get("f43"), price_precision),
            "open_price": self._scale_price(data.get("f46"), price_precision),
            "high_price": self._scale_price(data.get("f44"), price_precision),
            "low_price": self._scale_price(data.get("f45"), price_precision),
            "prev_close": self._scale_price(data.get("f60"), price_precision),
            "change_amount": self._scale_price(data.get("f169"), price_precision),
            "change_pct": self._scale_pct(data.get("f170")),
            "amplitude_pct": self._scale_pct(data.get("f171")),
            "turnover_pct": self._scale_pct(data.get("f168")),
            "volume": self._safe_float(data.get("f47")),
            "amount": self._safe_float(data.get("f48")),
            "market_status": self._safe_int(data.get("f292"), default=-1),
            "quote_timestamp": self._format_quote_ts(data.get("f86")),
        }
        return snapshot, self._build_resource_url(self._snapshot_url, params)

    def _fetch_trends(
        self,
        secid: str,
        ndays: int,
        max_points: int,
    ) -> tuple[List[Dict[str, Any]], str]:
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "iscr": "0",
            "iscca": "0",
            "secid": secid,
            "ndays": str(ndays),
        }
        points: List[Dict[str, Any]] = []
        try:
            response = self._session.get(
                self._trends_url,
                params=params,
                headers=self._headers,
                timeout=8.0,
            )
            payload = response.json() if response.status_code == 200 else {}
        except Exception:
            payload = {}

        if isinstance(payload, dict):
            data = payload.get("data") or {}
            rows = data.get("trends", []) if isinstance(data, dict) else []
            for line in rows:
                point = self._parse_trend_line(line)
                if point is not None:
                    points.append(point)
        if max_points > 0 and len(points) > max_points:
            points = points[-max_points:]
        return points, self._build_resource_url(self._trends_url, params)

    def _parse_trend_line(self, line: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(line, str):
            return None
        parts = line.split(",")
        if len(parts) < 8:
            return None
        try:
            return {
                "timestamp": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
                "avg_price": float(parts[7]),
            }
        except Exception:
            return None

    def _resolve_market_phase(self, market: MarketType) -> Dict[str, str]:
        timezone_map: Dict[MarketType, str] = {
            "cn_a": "Asia/Shanghai",
            "hk": "Asia/Hong_Kong",
            "us": "America/New_York",
        }
        timezone_name = timezone_map[market]
        now_local = dt.datetime.now(ZoneInfo(timezone_name))
        phase = self._phase_by_clock(market=market, now_local=now_local)
        return {
            "phase": phase,
            "timezone": timezone_name,
            "checked_at": now_local.isoformat(timespec="seconds"),
        }

    def _phase_by_clock(self, market: MarketType, now_local: dt.datetime) -> MarketPhase:
        if now_local.weekday() >= 5:
            return "closed"
        minute_of_day = now_local.hour * 60 + now_local.minute

        if market == "cn_a":
            if 9 * 60 + 15 <= minute_of_day < 9 * 60 + 30:
                return "pre_market"
            if (9 * 60 + 30 <= minute_of_day < 11 * 60 + 30) or (13 * 60 <= minute_of_day < 15 * 60):
                return "intraday"
            if 15 * 60 <= minute_of_day < 15 * 60 + 30:
                return "post_market"
            return "closed"

        if market == "hk":
            if 9 * 60 <= minute_of_day < 9 * 60 + 30:
                return "pre_market"
            if (9 * 60 + 30 <= minute_of_day < 12 * 60) or (13 * 60 <= minute_of_day < 16 * 60):
                return "intraday"
            if 16 * 60 <= minute_of_day < 16 * 60 + 10:
                return "post_market"
            return "closed"

        if 4 * 60 <= minute_of_day < 9 * 60 + 30:
            return "pre_market"
        if 9 * 60 + 30 <= minute_of_day < 16 * 60:
            return "intraday"
        if 16 * 60 <= minute_of_day < 20 * 60:
            return "post_market"
        return "closed"

    def _build_session_analysis(
        self,
        phase: MarketPhase,
        snapshot: Dict[str, Any],
        trend_points: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        latest_price = snapshot.get("latest_price")
        open_price = snapshot.get("open_price")
        prev_close = snapshot.get("prev_close")

        if open_price is None and trend_points:
            open_price = trend_points[0].get("open")
        high_price = snapshot.get("high_price")
        low_price = snapshot.get("low_price")

        if high_price is None and trend_points:
            high_price = max(point["high"] for point in trend_points)
        if low_price is None and trend_points:
            low_price = min(point["low"] for point in trend_points)

        metrics: Dict[str, Any] = {
            "phase": phase,
            "trend_points_count": len(trend_points),
        }
        if latest_price is not None and prev_close not in {None, 0}:
            metrics["latest_vs_prev_close_pct"] = round(
                (float(latest_price) - float(prev_close)) / float(prev_close) * 100,
                2,
            )
        if latest_price is not None and open_price not in {None, 0}:
            metrics["latest_vs_open_pct"] = round(
                (float(latest_price) - float(open_price)) / float(open_price) * 100,
                2,
            )
        if open_price not in {None, 0} and high_price is not None and low_price is not None:
            metrics["intraday_range_pct"] = round(
                (float(high_price) - float(low_price)) / float(open_price) * 100,
                2,
            )
        if trend_points:
            metrics["session_open"] = round(float(open_price), 6) if open_price is not None else None
            metrics["session_last"] = round(float(trend_points[-1]["close"]), 6)
            metrics["session_high"] = round(float(max(point["high"] for point in trend_points)), 6)
            metrics["session_low"] = round(float(min(point["low"] for point in trend_points)), 6)
            metrics["session_volume_total"] = round(float(sum(point["volume"] for point in trend_points)), 2)
            metrics["session_amount_total"] = round(float(sum(point["amount"] for point in trend_points)), 2)

        summary = self._build_phase_summary(phase=phase, metrics=metrics)
        if summary:
            metrics["summary"] = summary
        return metrics

    def _build_phase_summary(self, phase: MarketPhase, metrics: Dict[str, Any]) -> str:
        latest_vs_prev = metrics.get("latest_vs_prev_close_pct")
        latest_vs_open = metrics.get("latest_vs_open_pct")
        range_pct = metrics.get("intraday_range_pct")

        if phase == "pre_market":
            if latest_vs_prev is not None:
                return f"盘前相对昨收变动 {latest_vs_prev:.2f}%（以最新撮合价估算）。"
            return "盘前阶段：当前可用字段有限，建议关注开盘后前 15 分钟成交与价差。"
        if phase == "intraday":
            if latest_vs_open is not None and range_pct is not None:
                return f"盘中相对开盘 {latest_vs_open:.2f}%，日内振幅 {range_pct:.2f}%。"
            return "盘中阶段：可结合分钟线与成交量变化评估资金强弱。"
        if phase == "post_market":
            if latest_vs_prev is not None:
                return f"盘后收官相对昨收 {latest_vs_prev:.2f}%。"
            return "盘后阶段：可结合当日高低点复盘趋势与风险。"
        if latest_vs_prev is not None:
            return f"当前非交易时段，最近收盘相对昨收 {latest_vs_prev:.2f}%。"
        return "当前非交易时段。"

    def _build_session_points(
        self,
        snapshot: Dict[str, Any],
        trend_points: List[Dict[str, Any]],
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        prev_close = snapshot.get("prev_close")
        first_point = trend_points[0] if trend_points else None
        mid_point = trend_points[len(trend_points) // 2] if trend_points else None
        last_point = trend_points[-1] if trend_points else None
        session_open = first_point.get("open") if first_point else snapshot.get("open_price")

        session_points: Dict[str, Optional[Dict[str, Any]]] = {
            "pre_market": self._format_session_point(
                phase="pre_market",
                point=first_point,
                prev_close=prev_close,
                session_open=session_open,
            ),
            "intraday": self._format_session_point(
                phase="intraday",
                point=mid_point,
                prev_close=prev_close,
                session_open=session_open,
            ),
            "post_market": self._format_session_point(
                phase="post_market",
                point=last_point,
                prev_close=prev_close,
                session_open=session_open,
            ),
        }
        if session_points["post_market"] is None:
            fallback_price = snapshot.get("latest_price")
            if fallback_price is not None:
                session_points["post_market"] = {
                    "phase": "post_market",
                    "timestamp": snapshot.get("quote_timestamp"),
                    "price": round(float(fallback_price), 6),
                    "vs_prev_close_pct": self._calc_rel_pct(fallback_price, prev_close),
                    "vs_open_pct": self._calc_rel_pct(fallback_price, session_open),
                    "volume": snapshot.get("volume"),
                    "amount": snapshot.get("amount"),
                    "avg_price": None,
                }
        return session_points

    def _format_session_point(
        self,
        *,
        phase: MarketPhase,
        point: Optional[Dict[str, Any]],
        prev_close: Any,
        session_open: Any,
    ) -> Optional[Dict[str, Any]]:
        if point is None:
            return None
        price = point.get("close")
        payload: Dict[str, Any] = {
            "phase": phase,
            "timestamp": point.get("timestamp"),
            "price": round(float(price), 6) if price is not None else None,
            "vs_prev_close_pct": self._calc_rel_pct(price, prev_close),
            "vs_open_pct": self._calc_rel_pct(price, session_open),
            "volume": round(float(point["volume"]), 2) if point.get("volume") is not None else None,
            "amount": round(float(point["amount"]), 2) if point.get("amount") is not None else None,
            "avg_price": round(float(point["avg_price"]), 6) if point.get("avg_price") is not None else None,
        }
        return payload

    def _calc_rel_pct(self, latest: Any, base: Any) -> Optional[float]:
        latest_float = self._safe_float(latest)
        base_float = self._safe_float(base)
        if latest_float is None or base_float in {None, 0}:
            return None
        return round((latest_float - base_float) / base_float * 100.0, 4)

    def _safe_float(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(float(value))
        except Exception:
            return default

    def _scale_price(self, value: Any, precision: int) -> Optional[float]:
        raw = self._safe_float(value)
        if raw is None:
            return None
        factor = float(10 ** max(0, precision))
        return round(raw / factor, min(max(precision + 2, 2), 6))

    def _scale_pct(self, value: Any) -> Optional[float]:
        raw = self._safe_float(value)
        if raw is None:
            return None
        return round(raw / 100.0, 4)

    def _format_quote_ts(self, value: Any) -> Optional[str]:
        ts_int = self._safe_int(value, default=0)
        if ts_int <= 0:
            return None
        try:
            return dt.datetime.fromtimestamp(ts_int, tz=dt.timezone.utc).isoformat(timespec="seconds")
        except Exception:
            return None

    def _build_resource_url(self, url: str, params: Dict[str, Any]) -> str:
        prepared = requests.Request(method="GET", url=url, params=params).prepare()
        return prepared.url
