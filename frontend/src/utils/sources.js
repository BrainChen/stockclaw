const INVALID_URL_VALUES = new Set(["n/a", "na", "none", "null", "-", "#"]);

function normalizeExternalUrl(rawUrl) {
  if (typeof rawUrl !== "string") {
    return "";
  }
  const trimmed = rawUrl.trim();
  if (!trimmed) {
    return "";
  }
  if (INVALID_URL_VALUES.has(trimmed.toLowerCase())) {
    return "";
  }
  try {
    const parsed = new URL(trimmed);
    return /^https?:$/.test(parsed.protocol) ? parsed.toString() : "";
  } catch {
    return "";
  }
}

function extractSymbolFromSource(source) {
  const title = typeof source?.title === "string" ? source.title.trim() : "";
  if (!title) {
    return "";
  }
  const headMatch = title.match(/^\s*([A-Z0-9.^-]{1,15}(?:\.[A-Z]{1,4})?)\s*[-|：:]/);
  if (headMatch) {
    return headMatch[1].toUpperCase();
  }
  return "";
}

function toStooqSymbol(symbol) {
  const normalized = symbol.trim().toLowerCase();
  if (!normalized) {
    return "";
  }
  if (normalized.endsWith(".hk")) {
    const base = normalized.split(".")[0];
    if (/^\d+$/.test(base)) {
      return `${String(Number(base))}.hk`;
    }
    return `${base}.hk`;
  }
  if (normalized.endsWith(".us")) {
    return normalized;
  }
  if (/^[a-z]+$/.test(normalized)) {
    return `${normalized}.us`;
  }
  return normalized;
}

function getMarketFallbackUrl(source) {
  const symbol = extractSymbolFromSource(source);
  const lowerTitle = typeof source?.title === "string" ? source.title.toLowerCase() : "";
  const lowerContent = typeof source?.content === "string" ? source.content.toLowerCase() : "";
  const context = `${lowerTitle} ${lowerContent}`;

  if (symbol) {
    if (context.includes("stooq")) {
      return `https://stooq.com/q/?s=${encodeURIComponent(toStooqSymbol(symbol))}`;
    }
    if (context.includes("news") || context.includes("新闻")) {
      return `https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}/news`;
    }
    if (
      context.includes("history") ||
      context.includes("ohlcv") ||
      context.includes("market data") ||
      context.includes("行情")
    ) {
      return `https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}/history`;
    }
    return `https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}`;
  }

  if (context.includes("stooq")) {
    return "https://stooq.com/";
  }
  return "https://finance.yahoo.com/markets/";
}

export function getSourceHref(source) {
  const sourceUrl = normalizeExternalUrl(source?.url);
  if (sourceUrl) {
    return sourceUrl;
  }
  const sourcePath = typeof source?.path === "string" ? source.path.trim() : "";
  if (source?.source_type === "kb" && sourcePath) {
    return `/api/kb/document/preview?path=${encodeURIComponent(sourcePath)}`;
  }
  if (source?.source_type === "market") {
    return getMarketFallbackUrl(source);
  }
  const query = [source?.title, source?.source_type].filter(Boolean).join(" ");
  return `https://duckduckgo.com/?q=${encodeURIComponent(query || "financial market news")}`;
}

export function getSourceHost(source) {
  const sourcePath = typeof source?.path === "string" ? source.path.trim() : "";
  if (source?.source_type === "kb" && sourcePath) {
    return "知识库文档";
  }
  const sourceUrl = normalizeExternalUrl(source?.url);
  if (!sourceUrl) {
    if (source?.source_type === "market") {
      return "Yahoo Finance";
    }
    return "搜索结果";
  }
  try {
    return new URL(sourceUrl, window.location.origin).host.replace(/^www\./, "");
  } catch {
    return "外部链接";
  }
}

export function getSourceKey(source) {
  const sourceUrl = typeof source?.url === "string" ? source.url.trim().toLowerCase() : "";
  const sourcePath = typeof source?.path === "string" ? source.path.trim().toLowerCase() : "";
  const sourceTitle = typeof source?.title === "string" ? source.title.trim().toLowerCase() : "";
  const sourceType = typeof source?.source_type === "string" ? source.source_type.trim().toLowerCase() : "";
  return `${sourceUrl}|${sourcePath}|${sourceTitle}|${sourceType}`;
}
