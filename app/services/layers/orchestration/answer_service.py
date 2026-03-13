import re
from time import perf_counter
from typing import Dict, List

from app.common.logger import get_logger, kv, preview_text
from app.models.schemas import ChatResponse, SourceItem
from app.services.layers.integration.llm_service import LLMService
from app.models.query_dsl import QueryDSL
from app.common.market_rules import is_large_move, is_large_move_question, normalize_large_move_threshold
from app.services.layers.asset.market_service import MarketService
from app.services.layers.routing.query_interpreter_service import QueryInterpreterService
from app.services.layers.knowledge.rag_service import RAGService
from app.services.layers.knowledge.web_search_service import WebSearchService


class FinancialQAService:
    def __init__(self) -> None:
        self.query_interpreter = QueryInterpreterService()
        self.market_service = MarketService()
        self.rag_service = RAGService()
        self.web_search_service = WebSearchService()
        self.llm_service = LLMService()
        self.logger = get_logger(__name__)

    def ask(self, question: str) -> ChatResponse:
        started_at = perf_counter()
        self.logger.info("qa ask start %s", kv(question=preview_text(question, max_len=120)))
        query_dsl = self.query_interpreter.parse(question)
        self.logger.info(
            "qa route resolved %s",
            kv(route=query_dsl.route, symbol=query_dsl.symbol or "", dsl=query_dsl.to_expression()),
        )
        if query_dsl.route == "asset":
            response = self._answer_asset(question, query_dsl.symbol, query_dsl)
        else:
            response = self._answer_knowledge(question)
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        self.logger.info(
            "qa ask done %s",
            kv(route=response.route, symbol=response.symbol or "", source_count=len(response.sources), latency_ms=elapsed_ms),
        )
        return response

    def kb_stats(self) -> dict:
        return self.rag_service.get_stats()

    def reindex_kb(self, force: bool = True) -> dict:
        return self.rag_service.reindex(force=force)

    def search_kb(self, query: str, top_k: int = 5) -> list[Dict]:
        normalized_query = query.strip()
        if len(normalized_query) < 2:
            raise ValueError("检索词长度至少为 2 个字符。")
        return self.rag_service.retrieve(normalized_query, top_k=top_k)

    def _answer_asset(self, question: str, symbol: str | None, query_dsl: QueryDSL) -> ChatResponse:
        self.logger.info(
            "asset flow start %s",
            kv(symbol=symbol or "", window_days=query_dsl.window_days, event_date=query_dsl.event_date),
        )
        analysis_result = self.market_service.analyze(
            question=question,
            symbol=symbol,
            query_dsl=query_dsl,
        )
        source_dicts = analysis_result.sources
        answer = self._generate_asset_answer(
            question=question,
            symbol=analysis_result.symbol,
            objective_data=analysis_result.objective_data,
            analysis=analysis_result.analysis,
            sources=source_dicts,
        )
        response = ChatResponse(
            route="asset",
            symbol=analysis_result.symbol,
            answer=answer,
            objective_data=analysis_result.objective_data,
            analysis=analysis_result.analysis,
            sources=[SourceItem(**source) for source in source_dicts],
        )
        self.logger.info(
            "asset flow done %s",
            kv(
                symbol=response.symbol or "",
                data_provider=response.objective_data.get("data_provider"),
                fallback_used=response.objective_data.get("fallback_used"),
                source_count=len(response.sources),
            ),
        )
        return response

    def _answer_knowledge(self, question: str) -> ChatResponse:
        kb_hits = self.rag_service.retrieve(question, top_k=6, min_score=0.06)
        web_hits = self.web_search_service.search(question, max_results=4)
        unified_sources = self._build_knowledge_sources(kb_hits=kb_hits, web_hits=web_hits)
        self.logger.info(
            "knowledge retrieval %s",
            kv(kb_hits=len(kb_hits), web_hits=len(web_hits), merged_sources=len(unified_sources)),
        )

        answer = self._generate_knowledge_answer(question=question, sources=unified_sources)
        sources = [SourceItem(**item) for item in unified_sources]

        return ChatResponse(
            route="knowledge",
            answer=answer,
            objective_data={},
            analysis=[],
            sources=sources,
        )

    def _generate_asset_answer(
        self,
        question: str,
        symbol: str,
        objective_data: dict,
        analysis: List[str],
        sources: List[Dict],
    ) -> str:
        requested_window_days = objective_data.get("requested_window_days")
        requested_change = objective_data.get("requested_change_pct")
        event_query_date = objective_data.get("event_query_date")
        event_trade_date = objective_data.get("event_trade_date") or event_query_date
        event_change = objective_data.get("event_change_pct")
        event_has_data = bool(objective_data.get("event_has_data"))
        session_points = objective_data.get("session_three_points", {}) or {}
        large_move_threshold = normalize_large_move_threshold(
            objective_data.get("event_big_move_threshold_pct"),
            default=3.0,
        )
        is_event_large_move_question = is_large_move_question(question)
        has_event_focus = bool(event_query_date)
        if requested_window_days is not None and requested_change is not None:
            requested_window_text = f"近{requested_window_days}个交易日涨跌：{requested_change}%"
        elif has_event_focus and event_has_data and event_change is not None:
            requested_window_text = f"事件日 {event_trade_date} 单日涨跌：{event_change}%"
        elif has_event_focus:
            requested_window_text = f"事件日 {event_query_date}（需核验是否交易日）"
        else:
            requested_window_text = "未指定具体周期，默认关注近7日与近30日表现"

        event_instruction = (
            "若用户问题包含具体日期（如“1月15日”），直接结论必须先回答该事件日单日涨跌幅，"
            f"并在用户使用“大涨/大跌”等表述时明确判断是否达到常见阈值（约{large_move_threshold:.1f}%）。"
            "随后再补充近7日/14日/30日背景。"
            if has_event_focus
            else ""
        )
        session_instruction = (
            "若客观数据包含 session_three_points，必须单独给出盘前、盘中、盘尾三时刻的价格、"
            "相对昨收涨跌幅、量额信息；缺失字段要明确写“数据不足”。"
            if session_points
            else ""
        )
        prompt_objective_data = {
            key: value
            for key, value in objective_data.items()
            if key not in {"price_series", "volume_series"}
        }
        source_context = self._format_context_for_llm(sources, max_sources=6)
        system_prompt = (
            "你是专业金融分析助手。回答必须结构化，先给客观数据，再给分析描述。"
            "必须优先直接回答用户提到的时间周期（如7天/14天），不得用其他周期替代。"
            f"{event_instruction}"
            f"{session_instruction}"
            "如需引用来源，只能使用 [n] 形式（如 [1][2]），禁止输出裸数字引用（如 12 或 ¹²）。"
            "凡是引用客观行情、分时三时刻、新闻或数据源描述时，都应附上对应 [n] 引用。"
            "不得预测未来走势，不得编造数据。"
        )
        user_prompt = f"""
用户问题：{question}
股票代码：{symbol}
客观数据：{prompt_objective_data}
分析线索：{analysis}
可引用来源（已编号）：
{source_context}
用户关注周期：{requested_window_text}

请按以下格式输出：
1) 直接结论（先回答用户关注周期/事件日的涨跌幅，不超过2句）
2) 客观数据（日期、价格、7日涨跌、14日涨跌、30日涨跌、趋势；若存在事件日则补充事件日开高低收与单日涨跌；若存在 session_three_points 则补充盘前/盘中/盘尾三时刻）
3) 可能影响因素（至少4条，尽量覆盖：财报、宏观、行业/公司新闻、量价结构；若某角度证据不足需明确写“证据不足”）
4) 风险提示（1条）
"""
        llm_result = self.llm_service.generate(system_prompt, user_prompt)
        if llm_result:
            normalized = self._normalize_citations(llm_result, len(sources))
            if normalized:
                return normalized

        conclusion_lines = []
        market_citation = self._build_citation_markers([1, 2], len(sources))
        news_citations = self._build_citation_markers(
            list(range(3, min(len(sources), 6) + 1)),
            len(sources),
        )
        if has_event_focus:
            if event_has_data and event_change is not None:
                direction = "上涨" if float(event_change) >= 0 else "下跌"
                conclusion_lines.append(
                    f"- 事件日 {event_trade_date} 单日{direction} {abs(float(event_change)):.2f}%{market_citation}。"
                )
                if is_event_large_move_question:
                    if is_large_move(event_change, large_move_threshold):
                        conclusion_lines.append(
                            f"- 该幅度达到常见“大涨/大跌”（约≥{large_move_threshold:.1f}%）阈值{market_citation}。"
                        )
                    else:
                        conclusion_lines.append(
                            f"- 该幅度未达到常见“大涨/大跌”（约≥{large_move_threshold:.1f}%）阈值{market_citation}。"
                        )
            else:
                conclusion_lines.append(f"- 事件日 {event_query_date} 非交易日或数据不足，无法直接核验单日涨跌{market_citation}。")
            conclusion_lines.append(
                f"- 背景区间：近7日 {objective_data['change_7d_pct']}%，近30日 {objective_data['change_30d_pct']}%{market_citation}。"
            )
        elif requested_window_days is not None and requested_change is not None:
            conclusion_lines.append(
                f"- 近{requested_window_days}个交易日涨跌：{requested_change}%{market_citation}"
            )
        else:
            conclusion_lines.append(f"- 未识别到明确时间窗口，以下展示通用区间数据{market_citation}。")

        event_data_lines = []
        if has_event_focus:
            event_data_lines.append(f"- 事件查询日期：{event_query_date}{market_citation}")
            if event_has_data:
                event_data_lines.append(f"- 事件交易日：{event_trade_date}{market_citation}")
                if objective_data.get("event_open") is not None:
                    event_data_lines.append(f"- 事件日开盘：{objective_data.get('event_open')}{market_citation}")
                if objective_data.get("event_high") is not None:
                    event_data_lines.append(f"- 事件日最高：{objective_data.get('event_high')}{market_citation}")
                if objective_data.get("event_low") is not None:
                    event_data_lines.append(f"- 事件日最低：{objective_data.get('event_low')}{market_citation}")
                if objective_data.get("event_close") is not None:
                    event_data_lines.append(f"- 事件日收盘：{objective_data.get('event_close')}{market_citation}")
                if objective_data.get("event_change_pct") is not None:
                    event_data_lines.append(f"- 事件日单日涨跌：{objective_data.get('event_change_pct')}%{market_citation}")
                if objective_data.get("event_volume") is not None:
                    event_data_lines.append(f"- 事件日成交量：{objective_data.get('event_volume')}{market_citation}")
            else:
                previous_trade_date = objective_data.get("event_prev_trade_date")
                next_trade_date = objective_data.get("event_next_trade_date")
                if previous_trade_date:
                    event_data_lines.append(f"- 前一交易日：{previous_trade_date}{market_citation}")
                if next_trade_date:
                    event_data_lines.append(f"- 后一交易日：{next_trade_date}{market_citation}")

        session_lines = []
        session_phase_labels = {
            "pre_market": "盘前",
            "intraday": "盘中",
            "post_market": "盘尾",
        }
        for key in ["pre_market", "intraday", "post_market"]:
            point = session_points.get(key)
            label = session_phase_labels[key]
            if not isinstance(point, dict):
                session_lines.append(f"- {label}：数据不足{market_citation}")
                continue
            price = point.get("price")
            timestamp = point.get("timestamp") or "N/A"
            vs_prev_close_pct = point.get("vs_prev_close_pct")
            volume = point.get("volume")
            amount = point.get("amount")
            if price is None:
                session_lines.append(f"- {label}：数据不足{market_citation}")
                continue
            line = f"- {label}：时间 {timestamp}，价格 {price}"
            if vs_prev_close_pct is not None:
                line += f"，较昨收 {vs_prev_close_pct:+.2f}%"
            if volume is not None:
                line += f"，成交量 {volume}"
            if amount is not None:
                line += f"，成交额 {amount}"
            session_lines.append(f"{line}{market_citation}")

        return (
            f"【直接结论】\n"
            + "\n".join(conclusion_lines)
            + "\n\n"
            f"【客观数据】\n"
            f"- 标的：{symbol}{market_citation}\n"
            f"- 最新收盘价：{objective_data['latest_close']} {objective_data.get('currency', '')}{market_citation}\n"
            f"- 数据日期：{objective_data['latest_date']}{market_citation}\n"
            f"- 数据源：{objective_data.get('data_provider', 'unknown')}{market_citation}\n"
            f"- 分析置信度：{objective_data.get('analysis_confidence', 'N/A')}{market_citation}\n"
            f"- 近7日涨跌：{objective_data['change_7d_pct']}%{market_citation}\n"
            f"- 近14日涨跌：{objective_data.get('change_14d_pct', 0)}%{market_citation}\n"
            f"- 近30日涨跌：{objective_data['change_30d_pct']}%{market_citation}\n"
            f"- 近14日趋势：{objective_data['trend_14d']}{market_citation}\n"
            + ("\n".join(event_data_lines) + "\n" if event_data_lines else "")
            + ("\n".join(session_lines) + "\n" if session_lines else "")
            + "\n"
            f"【可能影响因素】\n"
            + "\n".join(
                [
                    f"- {item}{news_citations if index > 0 and news_citations else market_citation}"
                    for index, item in enumerate(analysis[:5])
                ]
            )
            + f"\n\n【风险提示】\n- 以上为历史数据与公开信息归纳，不构成投资建议{market_citation}。"
        )

    def _build_knowledge_sources(self, kb_hits: list, web_hits: list) -> list[Dict]:
        merged: list[Dict] = []
        seen_keys: set[str] = set()

        for item in kb_hits:
            normalized = {
                "source_type": "kb",
                "title": item.get("title", "Knowledge Base"),
                "content": item.get("content", ""),
                "url": item.get("url"),
                "score": item.get("score"),
                "path": item.get("path"),
                "chunk_id": item.get("chunk_id"),
            }
            dedupe_key = f"kb::{normalized['title']}::{normalized['content'][:120]}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            merged.append(normalized)

        for item in web_hits:
            normalized = {
                "source_type": "web",
                "title": item.get("title", "Web Search Result"),
                "content": item.get("snippet", ""),
                "url": item.get("url"),
                "score": None,
                "path": None,
                "chunk_id": None,
            }
            dedupe_key = f"web::{normalized['title']}::{normalized['url'] or normalized['content'][:120]}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            merged.append(normalized)
        return merged

    def _generate_knowledge_answer(self, question: str, sources: list[Dict]) -> str:
        if not sources:
            return "未检索到可用资料。请补充更具体的关键词（如指标名称、公司名、财报期）。"

        context = self._format_context_for_llm(sources)
        system_prompt = (
            "你是金融知识问答助手。必须只基于给定检索材料作答，不能补充未经检索的事实。"
            "如需引用来源，只能使用 [n] 形式（如 [1][2]），禁止输出裸数字引用（如 12 或 ¹²）。"
            "每个关键结论至少附一个引用。若证据不足，明确写“证据不足”。"
        )
        user_prompt = f"""
问题：{question}

检索材料（已编号）：
{context}

请输出：
1) 直接回答（先结论）
2) 关键依据（2-4条，每条带引用）
3) 不确定性与边界（若有）
"""
        llm_result = self.llm_service.generate(system_prompt, user_prompt)
        if llm_result:
            normalized = self._normalize_citations(llm_result, len(sources))
            if normalized:
                return normalized

        return self._build_grounded_fallback_answer(question=question, sources=sources)

    def _format_context_for_llm(self, sources: list[Dict], max_sources: int = 6) -> str:
        lines: list[str] = []
        for index, source in enumerate(sources[:max_sources], start=1):
            excerpt = self._truncate_text(source.get("content", ""), max_chars=260)
            if not excerpt:
                continue
            url = source.get("url") or "N/A"
            lines.append(
                f"[{index}] {source.get('title', 'Untitled')} | 类型: {source.get('source_type', 'unknown')} | 链接: {url}\n{excerpt}"
            )
        return "\n\n".join(lines) if lines else "无"

    def _build_grounded_fallback_answer(self, question: str, sources: list[Dict]) -> str:
        top_sources = sources[:4]
        direct_line = self._extract_key_sentence(top_sources[0].get("content", ""))
        if not direct_line:
            direct_line = "当前检索结果可用信息有限，暂无法给出高置信度结论。"

        lines = [
            "## 直接回答",
            f"{direct_line} [1]",
            "",
            "## 关键依据",
        ]
        for index, source in enumerate(top_sources, start=1):
            key_sentence = self._extract_key_sentence(source.get("content", ""))
            title = source.get("title", "Untitled")
            if key_sentence:
                lines.append(f"- {title}：{key_sentence} [{index}]")

        lines.extend(
            [
                "",
                "## 不确定性与边界",
                "- 以上回答严格基于检索片段，可能不包含最新公告或完整上下文。",
                "- 建议结合原始披露文件或权威数据库进一步核验。",
                "",
                f"（问题：{question}）",
            ]
        )
        return "\n".join(lines)

    def _truncate_text(self, text: str, max_chars: int = 240) -> str:
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if not clean:
            return ""
        return clean if len(clean) <= max_chars else f"{clean[:max_chars]}..."

    def _extract_key_sentence(self, text: str) -> str:
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if not clean:
            return ""
        parts = re.split(r"(?<=[。！？.!?；;])\s+", clean)
        for part in parts:
            normalized = part.strip(" -•\t")
            if len(normalized) >= 16:
                return self._truncate_text(normalized, max_chars=140)
        return self._truncate_text(clean, max_chars=140)

    def _normalize_citations(self, answer: str, source_count: int) -> str:
        if not answer:
            return ""
        if source_count <= 0:
            return answer.strip()

        def replace_out_of_range(match: re.Match[str]) -> str:
            marker = match.group(0)
            raw_number = match.group(1)
            number = int(raw_number)
            if 1 <= number <= source_count:
                return marker
            return ""

        normalized = answer.replace("\r\n", "\n")
        normalized = re.sub(r"\[(\d+)\]", replace_out_of_range, normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        if "[" not in normalized:
            normalized = f"{normalized}\n\n参考来源：[1]"
        return normalized

    def _build_citation_markers(self, indexes: List[int], source_count: int) -> str:
        valid_indexes = [index for index in indexes if 1 <= index <= source_count]
        if not valid_indexes:
            return ""
        return "".join([f"[{index}]" for index in valid_indexes])
