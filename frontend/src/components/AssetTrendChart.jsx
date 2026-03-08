import { useMemo, useState } from "react";

import { formatShortDate, formatVolume } from "../utils/formatters";

export default function AssetTrendChart({
  priceSeries,
  volumeSeries,
  symbol,
  currency,
  windowDays,
}) {
  const [metric, setMetric] = useState("close");
  const [hoverIndex, setHoverIndex] = useState(null);

  const parsedPricePoints = useMemo(
    () =>
      (Array.isArray(priceSeries) ? priceSeries : [])
        .map((item) => ({
          date: String(item?.date || ""),
          value: Number(item?.close),
        }))
        .filter((item) => item.date && Number.isFinite(item.value)),
    [priceSeries]
  );

  const parsedVolumePoints = useMemo(
    () =>
      (Array.isArray(volumeSeries) ? volumeSeries : [])
        .map((item) => ({
          date: String(item?.date || ""),
          value: Number(item?.volume),
        }))
        .filter((item) => item.date && Number.isFinite(item.value)),
    [volumeSeries]
  );

  const hasVolume = parsedVolumePoints.length >= 2;
  const effectiveMetric = metric === "volume" && hasVolume ? "volume" : "close";
  const points = effectiveMetric === "volume" ? parsedVolumePoints : parsedPricePoints;

  if (points.length < 2) {
    return null;
  }

  const width = 860;
  const height = 300;
  const paddingTop = 22;
  const paddingRight = 22;
  const paddingBottom = 38;
  const paddingLeft = 62;
  const plotWidth = width - paddingLeft - paddingRight;
  const plotHeight = height - paddingTop - paddingBottom;

  const values = points.map((item) => item.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const valueSpan = Math.max(0.0001, maxValue - minValue);

  const toX = (index) => paddingLeft + (index / (points.length - 1)) * plotWidth;
  const toY = (value) => paddingTop + ((maxValue - value) / valueSpan) * plotHeight;

  const linePoints = points
    .map((item, index) => `${toX(index).toFixed(2)},${toY(item.value).toFixed(2)}`)
    .join(" ");
  const areaPoints = `${paddingLeft},${height - paddingBottom} ${linePoints} ${
    toX(points.length - 1).toFixed(2)
  },${height - paddingBottom}`;

  const first = points[0];
  const last = points[points.length - 1];
  const directionUp = last.value >= first.value;
  const colorUp = "#1f9d55";
  const colorDown = "#d9363e";
  const lineColor = directionUp ? colorUp : colorDown;
  const areaColor = directionUp ? "rgba(31,157,85,0.22)" : "rgba(217,54,62,0.22)";
  const areaColorFade = directionUp ? "rgba(31,157,85,0.02)" : "rgba(217,54,62,0.02)";
  const gradientId = `trend-gradient-${(symbol || "asset").replace(
    /[^a-zA-Z0-9_-]/g,
    ""
  )}-${effectiveMetric}-${windowDays || points.length}`;
  const changePct =
    first.value === 0 ? 0 : ((last.value - first.value) / first.value) * 100;
  const midPoint = points[Math.floor(points.length / 2)];
  const activeIndex =
    hoverIndex === null
      ? points.length - 1
      : Math.min(Math.max(hoverIndex, 0), points.length - 1);
  const activePoint = points[activeIndex];
  const activeX = toX(activeIndex);
  const activeY = toY(activePoint.value);

  const formatMetricValue = (rawValue) => {
    if (effectiveMetric === "volume") {
      return formatVolume(rawValue);
    }
    return Number(rawValue).toFixed(2);
  };

  const handlePointerMove = (event) => {
    const svgRect = event.currentTarget.getBoundingClientRect();
    const relativeX = ((event.clientX - svgRect.left) / svgRect.width) * width;
    const clampedX = Math.max(paddingLeft, Math.min(width - paddingRight, relativeX));
    const ratio = (clampedX - paddingLeft) / plotWidth;
    const index = Math.round(ratio * (points.length - 1));
    setHoverIndex(index);
  };

  const handlePointerLeave = () => setHoverIndex(null);

  return (
    <div className="trend-chart-card">
      <div className="trend-chart-head">
        <div className="trend-chart-title">
          <strong>{symbol || "标的"} 趋势图</strong>
          <span>近 {windowDays || points.length} 个交易日</span>
        </div>
        <div className="trend-chart-controls">
          <button
            type="button"
            className={`trend-tab ${effectiveMetric === "close" ? "active" : ""}`}
            onClick={() => setMetric("close")}
          >
            收盘价
          </button>
          <button
            type="button"
            className={`trend-tab ${effectiveMetric === "volume" ? "active" : ""}`}
            onClick={() => hasVolume && setMetric("volume")}
            disabled={!hasVolume}
            title={hasVolume ? "切换到成交量" : "暂无可用成交量数据"}
          >
            成交量
          </button>
          <div className={`trend-change ${directionUp ? "up" : "down"}`}>
            {changePct >= 0 ? "+" : ""}
            {changePct.toFixed(2)}%
          </div>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="trend-chart-svg"
        role="img"
        aria-label="股票价格趋势图"
        onMouseMove={handlePointerMove}
        onMouseLeave={handlePointerLeave}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={areaColor} />
            <stop offset="100%" stopColor={areaColorFade} />
          </linearGradient>
        </defs>

        <line
          x1={paddingLeft}
          y1={paddingTop}
          x2={paddingLeft}
          y2={height - paddingBottom}
          className="chart-axis"
        />
        <line
          x1={paddingLeft}
          y1={height - paddingBottom}
          x2={width - paddingRight}
          y2={height - paddingBottom}
          className="chart-axis"
        />
        <text x={paddingLeft - 8} y={paddingTop + 4} className="chart-label" textAnchor="end">
          {formatMetricValue(maxValue)}
        </text>
        <text
          x={paddingLeft - 8}
          y={height - paddingBottom + 4}
          className="chart-label"
          textAnchor="end"
        >
          {formatMetricValue(minValue)}
        </text>

        <polygon points={areaPoints} fill={`url(#${gradientId})`} />
        <polyline
          points={linePoints}
          fill="none"
          stroke={lineColor}
          strokeWidth="2.8"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        <line
          x1={activeX}
          y1={paddingTop}
          x2={activeX}
          y2={height - paddingBottom}
          className="chart-hover-line"
        />
        <circle cx={activeX} cy={activeY} r="3.5" fill={lineColor} stroke="#fff" strokeWidth="1.2" />

        <text x={paddingLeft} y={height - 10} className="chart-label" textAnchor="start">
          {formatShortDate(first.date)}
        </text>
        <text
          x={(paddingLeft + width - paddingRight) / 2}
          y={height - 10}
          className="chart-label"
          textAnchor="middle"
        >
          {formatShortDate(midPoint.date)}
        </text>
        <text
          x={width - paddingRight}
          y={height - 10}
          className="chart-label"
          textAnchor="end"
        >
          {formatShortDate(last.date)}
        </text>

        <rect
          x={paddingLeft}
          y={paddingTop}
          width={plotWidth}
          height={plotHeight}
          fill="transparent"
          pointerEvents="all"
          onMouseMove={handlePointerMove}
          onMouseLeave={handlePointerLeave}
        />
      </svg>

      <div className="trend-chart-tooltip">
        <span>{formatShortDate(activePoint.date)}</span>
        <strong>
          {effectiveMetric === "volume"
            ? formatVolume(activePoint.value)
            : `${activePoint.value.toFixed(2)} ${currency || ""}`}
        </strong>
      </div>

      <div className="trend-chart-meta">
        <span>
          起点：{formatMetricValue(first.value)}{" "}
          {effectiveMetric === "close" ? currency || "" : ""}
        </span>
        <span>
          终点：{formatMetricValue(last.value)}{" "}
          {effectiveMetric === "close" ? currency || "" : ""}
        </span>
      </div>
    </div>
  );
}
