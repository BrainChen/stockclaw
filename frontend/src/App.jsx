import { useMemo, useState } from "react";

import AnswerMarkdown from "./components/AnswerMarkdown";
import AssetTrendChart from "./components/AssetTrendChart";
import SourceList from "./components/SourceList";
import { INTERNAL_OBJECTIVE_KEYS, QUICK_QUESTIONS } from "./constants/chat";
import {
  formatObjectiveValue,
  getObjectiveLabel,
} from "./utils/formatters";
import {
  attachCitationLinks,
  extractCitedNumbers,
  normalizeAnswerText,
} from "./utils/answerText";
import { getSourceKey } from "./utils/sources";

function normalizePriceSeries(rawSeries) {
  if (!Array.isArray(rawSeries)) {
    return [];
  }
  return rawSeries
    .map((item) => ({
      date: String(item?.date || ""),
      close: Number(item?.close),
    }))
    .filter((item) => item.date && Number.isFinite(item.close));
}

function normalizeVolumeSeries(rawSeries) {
  if (!Array.isArray(rawSeries)) {
    return [];
  }
  return rawSeries
    .map((item) => ({
      date: String(item?.date || ""),
      volume: Number(item?.volume),
    }))
    .filter((item) => item.date && Number.isFinite(item.volume));
}

export default function App() {
  const [question, setQuestion] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [kbStatsLoading, setKbStatsLoading] = useState(false);
  const [kbReindexLoading, setKbReindexLoading] = useState(false);
  const [answerData, setAnswerData] = useState(null);
  const [chatError, setChatError] = useState("");
  const [kbData, setKbData] = useState(null);
  const [kbError, setKbError] = useState("");

  const hasQuestion = question.trim().length > 0;
  const askDisabled = chatLoading || !hasQuestion;
  const kbActionDisabled = kbStatsLoading || kbReindexLoading;

  const objectiveItems = useMemo(() => {
    if (!answerData?.objective_data) {
      return [];
    }
    return Object.entries(answerData.objective_data).filter(
      ([key]) => !INTERNAL_OBJECTIVE_KEYS.has(key)
    );
  }, [answerData]);

  const rawSources = useMemo(() => answerData?.sources || [], [answerData]);

  const sourceEntries = useMemo(
    () =>
      rawSources.map((source, index) => ({
        number: index + 1,
        source,
        key: getSourceKey(source),
      })),
    [rawSources]
  );

  const uniqueSourceEntries = useMemo(() => {
    const seen = new Set();
    return sourceEntries.filter((entry) => {
      if (seen.has(entry.key)) {
        return false;
      }
      seen.add(entry.key);
      return true;
    });
  }, [sourceEntries]);

  const answerWithCitationLinks = useMemo(() => {
    if (!answerData?.answer) {
      return "";
    }
    const normalizedAnswer = normalizeAnswerText(answerData.answer, rawSources.length);
    return attachCitationLinks(normalizedAnswer, rawSources);
  }, [answerData, rawSources]);

  const citedReferences = useMemo(() => {
    if (!answerData?.answer) {
      return [];
    }
    const normalizedAnswer = normalizeAnswerText(answerData.answer, rawSources.length);
    const citedNumbers = extractCitedNumbers(normalizedAnswer);
    const citedEntries = citedNumbers
      .map((number) => sourceEntries[number - 1] || null)
      .filter(Boolean);
    const seen = new Set();
    return citedEntries.filter((entry) => {
      if (seen.has(entry.key)) {
        return false;
      }
      seen.add(entry.key);
      return true;
    });
  }, [answerData, sourceEntries, rawSources.length]);

  const sourceItems = useMemo(() => {
    if (citedReferences.length === 0) {
      return uniqueSourceEntries;
    }
    const citedKeys = new Set(citedReferences.map((entry) => entry.key));
    return uniqueSourceEntries.filter((entry) => !citedKeys.has(entry.key));
  }, [uniqueSourceEntries, citedReferences]);

  const requestedWindowDays = useMemo(() => {
    const rawDays = answerData?.objective_data?.requested_window_days;
    return typeof rawDays === "number" && rawDays > 0 ? rawDays : null;
  }, [answerData]);

  const priceSeries = useMemo(
    () => normalizePriceSeries(answerData?.objective_data?.price_series),
    [answerData]
  );

  const volumeSeries = useMemo(
    () => normalizeVolumeSeries(answerData?.objective_data?.volume_series),
    [answerData]
  );

  const chartWindowDays = useMemo(() => {
    const rawDays = answerData?.objective_data?.chart_window_days;
    if (typeof rawDays === "number" && rawDays > 0) {
      return rawDays;
    }
    if (typeof requestedWindowDays === "number" && requestedWindowDays > 0) {
      return requestedWindowDays;
    }
    return priceSeries.length || null;
  }, [answerData, requestedWindowDays, priceSeries.length]);

  async function handleAsk() {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || chatLoading) {
      return;
    }

    setChatLoading(true);
    setChatError("");
    setAnswerData(null);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmedQuestion }),
      });

      const data = await response.json();
      if (!response.ok) {
        setAnswerData(null);
        setChatError(data.detail || "请求失败，请稍后重试");
        return;
      }
      setAnswerData(data);
    } catch (error) {
      setAnswerData(null);
      setChatError(`请求异常: ${error.message}`);
    } finally {
      setChatLoading(false);
    }
  }

  async function handleGetKbStats() {
    if (kbStatsLoading || kbReindexLoading) {
      return;
    }
    setKbStatsLoading(true);
    setKbError("");

    try {
      const response = await fetch("/api/kb/stats");
      const data = await response.json();
      if (!response.ok) {
        setKbError(data.detail || "读取知识库状态失败");
        return;
      }
      setKbData(data);
    } catch (error) {
      setKbError(`读取失败: ${error.message}`);
    } finally {
      setKbStatsLoading(false);
    }
  }

  async function handleReindexKb() {
    if (kbStatsLoading || kbReindexLoading) {
      return;
    }
    setKbReindexLoading(true);
    setKbError("");

    try {
      const response = await fetch("/api/kb/reindex", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: true }),
      });
      const data = await response.json();
      if (!response.ok) {
        setKbError(data.detail || "重建知识库失败");
        return;
      }
      setKbData(data);
    } catch (error) {
      setKbError(`重建失败: ${error.message}`);
    } finally {
      setKbReindexLoading(false);
    }
  }

  function handleQuestionKeyDown(event) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      handleAsk();
    }
  }

  return (
    <div className="app-shell">
      <header className="hero">
        <h1>金融资产问答系统</h1>
        <p>融合资产行情、知识检索与结构化分析，快速得到可追溯答案。</p>
      </header>

      <main className="content-stack">
        <section className="panel ask-panel">
          <div className="panel-head">
            <h2>提问面板</h2>
            <span className="kbd-tip">⌘/Ctrl + Enter 快速提交</span>
          </div>

          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={handleQuestionKeyDown}
            placeholder="例如：小米最近 7 天涨跌情况如何？"
            className="question-input"
          />

          <div className="quick-questions">
            {QUICK_QUESTIONS.map((item) => (
              <button
                key={item}
                type="button"
                className="chip"
                onClick={() => setQuestion(item)}
              >
                {item}
              </button>
            ))}
          </div>

          <div className="action-row">
            <button
              type="button"
              className="btn primary"
              onClick={handleAsk}
              disabled={askDisabled}
            >
              {chatLoading ? "处理中..." : "提交问题"}
            </button>
            <button
              type="button"
              className="btn ghost"
              onClick={handleGetKbStats}
              disabled={kbActionDisabled}
            >
              {kbStatsLoading ? "读取中..." : "知识库统计"}
            </button>
            <button
              type="button"
              className="btn danger"
              onClick={handleReindexKb}
              disabled={kbActionDisabled}
            >
              {kbReindexLoading ? "重建中..." : "重建知识库索引"}
            </button>
          </div>
        </section>

        {(chatLoading || answerData || chatError) && (
          <section className="panel result-panel">
            <div className="panel-head">
              <h2>回答结果</h2>
              <div className="result-head-badges">
                {answerData?.route && (
                  <span className="route-badge">
                    路由：{answerData.route}
                    {answerData.symbol ? ` · 标的：${answerData.symbol}` : ""}
                  </span>
                )}
                {requestedWindowDays && (
                  <span className="window-badge">回答周期：近 {requestedWindowDays} 天</span>
                )}
              </div>
            </div>

            {chatLoading ? (
              <div className="loading-state" role="status" aria-live="polite">
                <span className="loading-spinner" aria-hidden="true" />
                <span className="loading-text">正在生成回答，请稍候...</span>
              </div>
            ) : chatError ? (
              <p className="error-text">{chatError}</p>
            ) : (
              <>
                {answerData?.route === "asset" && priceSeries.length > 1 && (
                  <div className="block">
                    <h3>价格趋势图</h3>
                    <AssetTrendChart
                      priceSeries={priceSeries}
                      volumeSeries={volumeSeries}
                      symbol={answerData?.symbol}
                      currency={answerData?.objective_data?.currency}
                      windowDays={chartWindowDays}
                    />
                  </div>
                )}

                <AnswerMarkdown text={answerWithCitationLinks} />

                <SourceList
                  title="文中引用链接"
                  entries={citedReferences}
                  keyPrefix="cite"
                />

                {objectiveItems.length > 0 && (
                  <div className="block">
                    <h3>客观数据</h3>
                    <div className="metric-grid">
                      {objectiveItems.map(([key, value]) => (
                        <article className="metric-item" key={key}>
                          <p>{getObjectiveLabel(key)}</p>
                          <strong>{formatObjectiveValue(key, value)}</strong>
                        </article>
                      ))}
                    </div>
                  </div>
                )}

                <SourceList title="数据来源" entries={sourceItems} keyPrefix="source" />
              </>
            )}
          </section>
        )}

        {(kbData || kbError) && (
          <section className="panel kb-panel">
            <div className="panel-head">
              <h2>知识库状态</h2>
            </div>
            {kbError ? (
              <p className="error-text">{kbError}</p>
            ) : (
              <pre className="json-block">{JSON.stringify(kbData, null, 2)}</pre>
            )}
          </section>
        )}
      </main>
    </div>
  );
}
