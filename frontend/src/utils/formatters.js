import { OBJECTIVE_LABELS } from "../constants/chat";

export function formatShortDate(dateText) {
  if (!dateText) {
    return "";
  }
  const text = String(dateText);
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return text.slice(5);
  }
  return text;
}

export function formatVolume(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "-";
  }
  if (Math.abs(numeric) >= 1_000_000_000) {
    return `${(numeric / 1_000_000_000).toFixed(2)}B`;
  }
  if (Math.abs(numeric) >= 1_000_000) {
    return `${(numeric / 1_000_000).toFixed(2)}M`;
  }
  if (Math.abs(numeric) >= 1_000) {
    return `${(numeric / 1_000).toFixed(2)}K`;
  }
  return `${Math.round(numeric)}`;
}

export function formatDisplayValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (Array.isArray(value) || (typeof value === "object" && value !== null)) {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toString() : value.toFixed(4);
  }
  return String(value);
}

export function getObjectiveLabel(key) {
  return OBJECTIVE_LABELS[key] || key;
}

export function formatObjectiveValue(key, value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (key === "event_has_data" || key === "event_is_large_move" || key === "fallback_used") {
    if (typeof value === "boolean") {
      return value ? "是" : "否";
    }
    return String(value);
  }
  if (key === "analysis_confidence") {
    const numberValue = Number(value);
    if (Number.isFinite(numberValue)) {
      return `${(numberValue * 100).toFixed(0)}%`;
    }
  }
  if (key === "event_volume") {
    return formatVolume(value);
  }
  if (key.endsWith("_pct")) {
    const numberValue = Number(value);
    if (Number.isFinite(numberValue)) {
      return `${Number.isInteger(numberValue) ? numberValue : numberValue.toFixed(2)}%`;
    }
  }
  if (key === "latest_close") {
    const numberValue = Number(value);
    if (Number.isFinite(numberValue)) {
      return Number.isInteger(numberValue) ? String(numberValue) : numberValue.toFixed(2);
    }
  }
  return formatDisplayValue(value);
}
