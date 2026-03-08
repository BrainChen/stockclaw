# 小型金融知识库说明

该目录用于本地 RAG 检索，目标是覆盖常见“金融概念解释类”问题。

## 当前知识主题

- 估值与财务指标（PE / PB / PEG / ROE / ROIC）
- 财报与经营质量（收入、利润、现金流、同比/环比）
- 宏观变量传导（利率、通胀、汇率、流动性）
- 固收与利率风险（久期、凸性、信用利差）
- 风险管理与资产配置（波动率、回撤、相关性、再平衡）
- 衍生品与对冲（Delta、Gamma、Vega、套保）

## 索引与检索方式

1. 文档切片：按标题分段，再按 `KB_CHUNK_SIZE` 做滑窗分块。
2. 向量化：词级 TF-IDF + 字符级 TF-IDF 混合向量。
3. 检索：余弦相似度排序，返回相关片段用于回答生成。
4. Web 补充：对于时效性内容，额外使用 Web Search 检索。

## 使用方式

- 查看索引状态：`GET /api/kb/stats`
- 触发重建索引：`POST /api/kb/reindex`
- 调试向量检索：`POST /api/kb/search`
- 在线预览文档：`GET /api/kb/document/preview?path=...`

## 维护建议

- 每个文档控制在一个主题内，减少跨主题噪声。
- 优先使用“定义 + 公式 + 解释 + 场景”的结构。
- 避免放入没有时间戳的结论性观点，降低过时风险。

## 已约定目录

- 本地手工知识：`app/data/knowledge_base/*.md`
- 网络批量语料：`app/data/knowledge_base/web_finance/*.md`
- FAISS 持久化索引：`app/data/.kb_index`（环境变量：`KB_INDEX_DIR`）
