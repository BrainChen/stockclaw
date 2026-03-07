from typing import List

from app.models.schemas import ChatResponse, SourceItem
from app.services.llm_service import LLMService
from app.services.market_service import MarketService
from app.services.rag_service import RAGService
from app.services.router_service import QueryRouter
from app.services.web_search_service import WebSearchService


class FinancialQAService:
    def __init__(self) -> None:
        self.router = QueryRouter()
        self.market_service = MarketService()
        self.rag_service = RAGService()
        self.web_search_service = WebSearchService()
        self.llm_service = LLMService()

    def ask(self, question: str) -> ChatResponse:
        route_result = self.router.route(question)
        if route_result.route == "asset":
            return self._answer_asset(question, route_result.symbol)
        return self._answer_knowledge(question)

    def kb_stats(self) -> dict:
        return self.rag_service.get_stats()

    def reindex_kb(self, force: bool = True) -> dict:
        return self.rag_service.reindex(force=force)

    def _answer_asset(self, question: str, symbol: str | None) -> ChatResponse:
        analysis_result = self.market_service.analyze(question=question, symbol=symbol)
        answer = self._generate_asset_answer(
            question=question,
            symbol=analysis_result.symbol,
            objective_data=analysis_result.objective_data,
            analysis=analysis_result.analysis,
        )
        return ChatResponse(
            route="asset",
            symbol=analysis_result.symbol,
            answer=answer,
            objective_data=analysis_result.objective_data,
            analysis=analysis_result.analysis,
            sources=[SourceItem(**source) for source in analysis_result.sources],
        )

    def _answer_knowledge(self, question: str) -> ChatResponse:
        kb_hits = self.rag_service.retrieve(question, top_k=6)
        web_hits = self.web_search_service.search(f"finance {question}", max_results=3)

        answer = self._generate_knowledge_answer(question, kb_hits, web_hits)
        sources = [SourceItem(**item) for item in kb_hits]
        for web_item in web_hits:
            sources.append(
                SourceItem(
                    source_type="web",
                    title=web_item["title"],
                    content=web_item["snippet"],
                    url=web_item["url"],
                    score=None,
                )
            )

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
    ) -> str:
        system_prompt = (
            "你是专业金融分析助手。回答必须结构化，先给客观数据，再给分析描述。"
            "不得预测未来走势，不得编造数据。"
        )
        user_prompt = f"""
用户问题：{question}
股票代码：{symbol}
客观数据：{objective_data}
分析线索：{analysis}

请按以下格式输出：
1) 客观数据（日期、价格、7日涨跌、30日涨跌、趋势）
2) 可能影响因素（2-3条）
3) 风险提示（1条）
"""
        llm_result = self.llm_service.generate(system_prompt, user_prompt)
        if llm_result:
            return llm_result

        return (
            f"【客观数据】\n"
            f"- 标的：{symbol}\n"
            f"- 最新收盘价：{objective_data['latest_close']} {objective_data.get('currency', '')}\n"
            f"- 数据日期：{objective_data['latest_date']}\n"
            f"- 近7日涨跌：{objective_data['change_7d_pct']}%\n"
            f"- 近30日涨跌：{objective_data['change_30d_pct']}%\n"
            f"- 近14日趋势：{objective_data['trend_14d']}\n\n"
            f"【可能影响因素】\n"
            + "\n".join([f"- {item}" for item in analysis[:3]])
            + "\n\n【风险提示】\n- 以上为历史数据与公开信息归纳，不构成投资建议。"
        )

    def _generate_knowledge_answer(self, question: str, kb_hits: list, web_hits: list) -> str:
        context_kb = "\n\n".join([f"[KB]{item['title']}\n{item['content']}" for item in kb_hits[:3]])
        context_web = "\n\n".join(
            [f"[WEB]{item['title']}\n{item['snippet']}\n链接：{item['url']}" for item in web_hits[:2]]
        )
        system_prompt = (
            "你是金融知识问答助手。请基于给定检索材料回答，明确区分事实和解释。"
            "如果检索信息不足，要明确说明。"
        )
        user_prompt = f"""
问题：{question}

知识库检索：
{context_kb if context_kb else "无"}

Web检索：
{context_web if context_web else "无"}

请输出：
1) 直接回答
2) 关键要点（2-4条）
3) 若信息不足，补充说明不确定性
"""
        llm_result = self.llm_service.generate(system_prompt, user_prompt)
        if llm_result:
            return llm_result

        if not kb_hits and not web_hits:
            return "未检索到可用资料。请补充更具体的问题关键词（如公司名、财报季度、指标名称）。"

        lines = ["【直接回答】", "基于检索资料，相关概念如下：", "", "【关键要点】"]
        for item in kb_hits[:3]:
            lines.append(f"- {item['content'][:140]}...")
        for item in web_hits[:2]:
            lines.append(f"- {item['title']}：{item['snippet'][:110]}...")
        lines.append("")
        lines.append("【不确定性说明】")
        lines.append("- 回答来自知识库与公开网页摘要，建议进一步核对原始披露文件。")
        return "\n".join(lines)
