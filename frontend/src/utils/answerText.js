import { getSourceHref } from "./sources";

function countStrongMarkers(line) {
  return (line.match(/\*\*/g) || []).length;
}

function closeLeadingStrongBeforeColon(line) {
  if (!line.startsWith("**")) {
    return line;
  }
  const colonIndex = line.search(/[：:]/);
  if (colonIndex <= 2) {
    return line;
  }
  if (line.slice(2, colonIndex).includes("**")) {
    return line;
  }
  return `${line.slice(0, colonIndex)}**${line.slice(colonIndex)}`;
}

function removeLastStrongMarker(line) {
  const markerIndex = line.lastIndexOf("**");
  if (markerIndex < 0) {
    return line;
  }
  return `${line.slice(0, markerIndex)}${line.slice(markerIndex + 2)}`;
}

function normalizeBrokenBoldInLine(line) {
  if (!line || !line.includes("**")) {
    return line;
  }

  let normalized = line
    .replace(/\*\*\s+/g, "**")
    .replace(/\s+\*\*/g, "**")
    .replace(/\*\*\*/g, "**");

  normalized = closeLeadingStrongBeforeColon(normalized);

  if (countStrongMarkers(normalized) % 2 === 1) {
    normalized = removeLastStrongMarker(normalized);
  }
  if (countStrongMarkers(normalized) % 2 === 1) {
    normalized = normalized.replace("**", "");
  }
  return normalized;
}

export function attachCitationLinks(answer, sources) {
  if (!answer) {
    return "";
  }
  return answer.replace(/\[(\d+)\](?!\()/g, (raw, rawNumber) => {
    const index = Number(rawNumber) - 1;
    if (!Number.isInteger(index) || index < 0 || index >= sources.length) {
      return raw;
    }
    const href = getSourceHref(sources[index]);
    return `[${rawNumber}](${href})`;
  });
}

export function extractCitedNumbers(answer) {
  const matches = answer.match(/\[(\d+)\](?!\()/g) || [];
  const seen = new Set();
  const result = [];
  for (const marker of matches) {
    const number = Number(marker.slice(1, -1));
    if (Number.isInteger(number) && number > 0 && !seen.has(number)) {
      seen.add(number);
      result.push(number);
    }
  }
  return result;
}

export function normalizeAnswerText(answer, sourceCount) {
  if (!answer) {
    return "";
  }
  const maxCitation = Math.max(0, sourceCount);
  const normalizeBoldMarkers = (text) =>
    text
      .split("\n")
      .map((line) => normalizeBrokenBoldInLine(line))
      .join("\n")
      .replace(/\*\*([^*\n]+?)\*\*/g, (_, content) => `**${content.trim()}**`)
      .replace(/([0-9%）)])\*\*([^*\n]{1,80}?)\*\*([0-9（(])/g, "$1 $2 $3")
      .replace(/([^\s])\*\*([^*\n]+?)\*\*/g, "$1 **$2**")
      .replace(/\*\*([^*\n]+?)\*\*(\[[0-9]+\]|[A-Za-z0-9\u4e00-\u9fff])/g, "**$1** $2");

  const cleaned = answer
    .replace(/\r\n/g, "\n")
    .replace(/\[(分析线索|分析|analysis)\]/gi, "")
    .replace(/[ \t]{3,}/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n");

  const normalizedBold = normalizeBoldMarkers(cleaned);
  const formatted = normalizedBold
    .replace(/\[(\d+)\](?!\()/g, (raw, rawNumber) => {
      const number = Number(rawNumber);
      if (!Number.isInteger(number) || number < 1 || number > maxCitation) {
        return "";
      }
      return raw;
    })
    .replace(
      /(^|\n)\s*\d+[)．。、.]\s*\n\s*(直接结论|客观数据|可能影响因素|风险提示)\s*[:：]?\s*/g,
      "$1## $2\n"
    )
    .replace(
      /(^|\n)\s*\d+[)．。、.]\s*(直接结论|客观数据|可能影响因素|风险提示)\s*[:：]?\s*/g,
      "$1## $2\n"
    )
    .replace(/[ \t]{2,}/g, " ")
    .replace(/([^\n])\s+(直接结论|客观数据|可能影响因素|风险提示)(?=\s|[:：])/g, "$1\n\n$2")
    .replace(/(^|\n)(直接结论|客观数据|可能影响因素|风险提示)\s*[:：]?\s*/g, "$1## $2\n")
    .replace(/^\s*(\d+)\.\s*\n\s*(?=\S)/gm, "$1. ")
    .replace(/^\s*(\d+)\)\s*\n\s*(?=\S)/gm, "$1) ")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]+$/gm, "");

  return formatted;
}

export function getNodeText(children) {
  if (typeof children === "string") {
    return children;
  }
  if (typeof children === "number") {
    return String(children);
  }
  if (Array.isArray(children)) {
    return children.map((child) => getNodeText(child)).join("");
  }
  if (children && typeof children === "object" && "props" in children) {
    return getNodeText(children.props?.children);
  }
  return "";
}
