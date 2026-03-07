# 通用知识库说明

该目录作为通用 RAG 语料根目录，支持递归扫描子目录并建立索引。

## 支持格式

- `.md`
- `.txt`
- `.json`
- `.csv`
- `.pdf`（需安装 `pypdf`）

## 使用建议

1. 将你自己的金融文档按主题放入该目录（可建子目录）。
2. 点击前端“重建知识库索引”或调用 `POST /api/kb/reindex`。
3. 使用 `GET /api/kb/stats` 查看已索引文件数与切片数。

## 推荐语料组织

```text
knowledge_base/
├── macro/
├── equity/
├── fixed_income/
├── derivatives/
├── accounting/
└── regulation/
```
