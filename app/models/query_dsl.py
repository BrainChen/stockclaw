import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Literal, Optional


RouteType = Literal["asset", "knowledge"]


@dataclass
class QueryDSL:
    route: RouteType
    question: str
    symbol: Optional[str] = None
    window_days: Optional[int] = None
    event_date: Optional[dt.date] = None
    metrics: list[str] = field(default_factory=list)
    need_news: bool = False
    check_large_move: bool = False
    confidence: float = 0.0

    def to_expression(self) -> str:
        args: list[str] = [f'route="{self.route}"']
        if self.symbol:
            args.append(f'symbol="{self.symbol}"')
        if self.window_days is not None:
            args.append(f"window_days={self.window_days}")
        if self.event_date is not None:
            args.append(f'event_date="{self.event_date.isoformat()}"')
        if self.metrics:
            metrics_repr = ",".join(self.metrics)
            args.append(f'metrics="[{metrics_repr}]"')
        args.append(f"need_news={str(self.need_news).lower()}")
        args.append(f"check_large_move={str(self.check_large_move).lower()}")
        args.append(f"confidence={self.confidence:.2f}")
        return f'QUERY({", ".join(args)})'

    def to_dict(self) -> dict:
        payload = asdict(self)
        if isinstance(payload.get("event_date"), dt.date):
            payload["event_date"] = payload["event_date"].isoformat()
        payload["dsl"] = self.to_expression()
        return payload
