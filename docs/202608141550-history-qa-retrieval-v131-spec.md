# EduAgent 历史问答检索质量优化 v1.31 Spec

**创建时间：** 2026-08-14 15:50  
**状态：** Engineering Complete（生产索引重建、教研 reviewed 标签与灰度证据待完成）  
**目标版本：** v1.31.0（检索契约与评测）+ v1.31.1（混合召回与语料工程）+ v1.31.2（证据门控与灰度）  
**优先级：** P0  
**适用范围：** `随问 · 学习助手` 的历史问答、教材问答、基于史料出题；复用现有 Router / Planner / Runtime、pgvector、BM25、Answer Verifier、AgentOps 和 Release Gate  
**前置基线：** commit `c58d875`  
**关联文档：**

- `docs/202608141024-agent-intelligence-evidence-rollout-v130-spec.md`
- `docs/202608131651-agent-intelligence-upgrade-v129-spec.md`
- `docs/20260604-pep-history-textbook-knowledge-base.md`
- `docs/202606291600-autotutor-deploy-dev.md`

---

## 0. 决策摘要

当前项目已经具备 pgvector、关键词检索、BM25、向量召回、可选 cross-encoder、来源级答案验证和 2850 条历史教材语料，不需要重建一套新的 RAG 框架。

本轮真实问答暴露的主要问题不是“没有向量检索”，而是以下契约没有闭环：

1. 查询中的实体、问答维度和课程范围没有稳定结构化，`长平之战的意义` 可能被整体当成 topic。
2. 当前 hybrid 将向量名次分与自定义关键词分直接相加，不同通道分数不可校准，也不是标准 RRF。
3. cross-encoder 只有设置 `RERANK_MODEL_PATH` 才会启用，运行结果没有明确暴露 `enabled / skipped / failed`。
4. `corpus.json` 中存在长 OCR 段落、主题过宽和一段多知识点；`geo_events.json` 有事件事实，但没有进入统一 history 索引。
5. 工具 `ok=true` 只表示调用完成，空结果或弱证据仍可能在 UI 显示“史料检索 已完成”。
6. 当前检索评测只有 5 个基础 case，无法覆盖实体问法、维度问法、跨轮追问、无答案和相似实体干扰。

v1.31 采用“领域结构化查询 + 多路候选召回 + RRF + 维度感知重排 + 证据门控”的演进方案：

```text
用户问题 + 会话/教材上下文
  -> HistoryQuery 解析
       entity: 长平之战
       aspect: significance
       question_type: explanation
       scope: 七年级上 / 第6课（可选）
  -> 并行候选召回
       A. entity / alias / metadata 精确通道
       B. BM25 全文通道
       C. pgvector 语义通道
  -> Reciprocal Rank Fusion
  -> aspect-aware reranker
  -> evidence sufficiency gate
       sufficient -> grounded answer
       partial    -> 限定范围回答并说明证据边界
       none       -> 明确无足够教材依据，不生成事实答案
```

本轮不直接引入 GraphRAG。当前失败主要是单事件、单人物的实体定位、语料覆盖和答案维度匹配；知识图谱只在后续评测证明存在大量跨实体、多跳关系问题时再立项。

---

## 1. 当前项目基线

### 1.1 已有能力

| 能力 | 当前实现 | 结论 |
| --- | --- | --- |
| 历史语料 | `knowledge_base/history/corpus.json`，2850 条 | 数量足够做质量治理，但粒度不一致 |
| 事件事实 | `knowledge_base/history/geo_events.json`，158 条 | 有补充价值，当前未进入 history 索引 |
| 向量存储 | Postgres + pgvector，`rag_documents` | 保留 |
| Embedding | OpenAI-compatible 托管接口，默认 1024 维 | 保留，版本需写入索引清单 |
| 关键词/BM25 | `backend/rag/knowledge_base.py` | 保留召回能力，改造融合方式 |
| Cross encoder | `backend/rag/rerank.py` | 可选但默认不可观测，需要显式运行状态 |
| 历史搜索工具 | `backend/tools/history_search.py` | 已具备 topic 过滤和 aspect 初步排序 |
| 答案验证 | `backend/agents/answer_verifier.py` | 已有 source ID 与 claim 验证，增加证据充分性前置门控 |
| 检索评测 | `eval/rag_retrieval_eval.py`，5 cases | 不足以作为发布门禁 |
| 专项回归 | `eval/history_search_relevance_smoke.py` | 已覆盖本轮苏轼/赤壁相关修复 |

### 1.2 已确认的语料问题

- `长平之战` 在 `corpus.json` 中只有一条直接命中，内容仅说明其属于战国兼并战争，没有直接回答其意义。
- `geo_events.json` 包含“赵国元气大伤”等事件结果，但其来源等级和教材出处尚未建立，不能冒充教材原文。
- `苏轼`、`赤壁之战` 等词可能出现在包含多个历史对象的长 OCR 段落中，导致召回命中但答案维度不命中。
- 当前索引脚本使用递归文本切分，chunk ID 为运行序号；语料重排后 ID 会变化，不利于稳定引用和增量更新。

### 1.3 本轮基线验证

commit `c58d875` 已通过：

- `history_search_relevance_smoke=PASS`；
- `learning_assistant_multiturn_smoke=PASS`；
- `trajectory_eval=5/5`；
- 前端 `learningAssistantComposer` 6/6 单测；
- fast release gate：20/20 suites、377/377 cases。

这些结果证明当前修复没有破坏主路径，但不证明真实历史问答检索质量达到发布目标。

---

## 2. 目标与非目标

### 2.1 产品目标

1. 同一知识点的“原因、经过、结果、影响、意义、评价”等问法能够命中回答该维度的证据，而不是只命中实体名称。
2. 多轮中的“结合教材解释”“它有什么影响”能够继承可信实体和教材范围，不要求学生重复课名。
3. 无足够教材依据时诚实说明证据边界，避免用邻近知识或常识拼接成确定答案。
4. 刷新后保留检索来源摘要、来源等级和证据状态；重复 repair 不产生重复工具卡。
5. 回答保持 2-4 句的学习场景表达，不把内部检索流程暴露给学生。

### 2.2 工程目标

- 建立稳定的 `HistoryQuery`、`HistorySource`、`RetrievalDiagnostics` 和 `EvidenceSufficiency` 契约。
- 精确、BM25、向量三个通道独立产出 rank，再用 RRF 融合；禁止直接相加不可校准原始分数。
- reranker 是否启用、使用何种模型、耗时与失败原因可追踪。
- 建立教材段落、原子事实、补充事件事实三层文档，并统一稳定 source ID、来源等级和版本。
- 增加不少于 120 条 reviewed 检索集和不少于 40 条无答案/干扰集。
- 将检索质量指标接入 core eval、报告和灰度回滚信号。

### 2.3 非目标

- 不接入开放网页搜索。
- 不以 LLM 作为唯一实体解析器或唯一正确性裁判。
- 不重写学习助手 Router / Planner / Runtime。
- 不在 v1.31 引入 GraphRAG、知识图谱数据库或开放式多跳 Agent。
- 不把 `geo_events.json` 的内容自动标记为教材原文。
- 不一次性人工重写全部 2850 条语料；优先覆盖高频教材事件和评测失败项。

---

## 3. 成功指标

### 3.1 查询解析

| 指标 | v1.31 门槛 | 阻断条件 |
| --- | ---: | --- |
| entity exact accuracy | `>= 96%` | `< 94%` |
| aspect macro-F1 | `>= 92%` | `< 88%` |
| scope inheritance accuracy | `>= 95%` | `< 92%` |
| unresolved ambiguous query precision | `>= 90%` | 错实体直接执行 |

### 3.2 检索质量

| 指标 | v1.31 门槛 | 说明 |
| --- | ---: | --- |
| entity Recall@5 | `>= 98%` | top 5 至少包含正确实体来源 |
| aspect Recall@5 | `>= 92%` | top 5 至少有一条回答目标维度 |
| answer-bearing Recall@5 | `>= 90%` | 有答案 case 中存在可直接支持答案的来源 |
| nDCG@5 | `>= 0.85` | 相关性分级为 0/1/2 |
| MRR@5 | `>= 0.88` | 首条可用证据排名 |
| unrelated top-3 rate | `<= 3%` | top 3 含无关实体的 case 比例 |
| no-answer precision | `>= 95%` | 无证据时不误报有答案 |

### 3.3 回答与运行

| 指标 | 门槛 |
| --- | ---: |
| citation/source ID validity | `100%` |
| supported critical claim coverage | `>= 95%` |
| unsupported critical claim rate | `<= 2%` |
| no-evidence completed rate | `0%` |
| retrieval p95（不含首次模型下载） | `<= 900ms` |
| rerank p95 | `<= 350ms` |
| 历史问答端到端 p95 | `<= 4.5s` |
| fallback / degraded 原因可观测率 | `100%` |

---

## 4. 查询理解契约

### 4.1 `HistoryQuery`

新增 `backend/rag/history_query.py`：

```python
class HistoryQuery(BaseModel):
    schema_version: Literal[1] = 1
    original_query: str
    retrieval_query: str
    entity: str | None = None
    entity_type: Literal["event", "person", "dynasty", "institution", "concept", "place", "unknown"] = "unknown"
    aliases: list[str] = Field(default_factory=list)
    aspect: Literal[
        "definition", "background", "cause", "process", "result",
        "impact", "significance", "measure", "contribution",
        "feature", "comparison", "evaluation", "fact", "unknown"
    ] = "unknown"
    question_type: Literal["fact", "explanation", "comparison", "evaluation", "quiz", "unknown"] = "unknown"
    grade: str | None = None
    lesson: str | None = None
    inherited_from_context: bool = False
    confidence: float = 0.0
    needs_clarification: bool = False
    reason_codes: list[str] = Field(default_factory=list)
```

### 4.2 解析顺序

```text
可信 source_context / 已确认待补槽位
  -> 课程与年级范围
实体词典 exact / alias match
  -> entity + entity_type
确定性维度词表
  -> aspect
历史会话中的最近可信实体
  -> 仅用于代词、教材动作和省略问法
可选结构化 LLM fallback
  -> 只能从候选实体和枚举 aspect 中选择
低置信或多候选
  -> clarification，不执行检索答案生成
```

约束：

- `长平之战的意义` 必须解析为 `entity=长平之战`、`aspect=significance`。
- `为什么会失败` 在没有可信上下文时必须澄清；不得把“失败”当实体。
- `苏轼做了什么` 必须优先识别人物贡献，不允许将“辛弃疾继承苏轼词风”当成苏轼本人行为。
- 解析器不得通过删除任意尾缀生成未知实体；最终 entity 必须命中实体目录、教材 metadata 或高置信候选。

### 4.3 实体目录

新增 `knowledge_base/history/entities.json`，由 corpus metadata、`geo_events.json` 和 reviewed alias 合并生成：

```json
{
  "entity_id": "event.changping_battle",
  "canonical_name": "长平之战",
  "entity_type": "event",
  "aliases": ["长平大战"],
  "grades": ["七年级上"],
  "lessons": ["第6课 战国时期的社会变革"],
  "source_refs": ["history-textbook-...", "geo-event-battle_changping"]
}
```

别名必须人工 reviewed；不得把模型临时生成的别名直接写入生产目录。

---

## 5. 文档与索引设计

### 5.1 三层文档

| 层级 | `document_type` | 用途 | 来源等级 |
| --- | --- | --- | --- |
| 教材上下文 | `textbook_passage` | 保留原始段落和上下文 | `L1_TEXTBOOK_DIRECT` |
| 原子事实 | `textbook_fact` | 精确回答原因/影响等维度 | `L1_TEXTBOOK_DIRECT` 或 `L2_TEXTBOOK_DERIVED` |
| 补充事实 | `curated_event_fact` | 补齐教材未直接展开的事件信息 | `L3_CURATED_REFERENCE` |

`L2_TEXTBOOK_DERIVED` 必须保存其父教材片段，且事实只能是忠实拆分或摘要；`L3` 必须明确显示为补充资料，不能生成教材页码。

### 5.2 `HistorySource`

```python
class HistorySource(BaseModel):
    source_id: str
    parent_source_id: str | None = None
    document_type: Literal["textbook_passage", "textbook_fact", "curated_event_fact"]
    source_tier: Literal["L1_TEXTBOOK_DIRECT", "L2_TEXTBOOK_DERIVED", "L3_CURATED_REFERENCE"]
    entity_id: str | None = None
    entity: str | None = None
    aliases: list[str] = Field(default_factory=list)
    aspect: str = "fact"
    claim: str
    context: str | None = None
    grade: str | None = None
    unit: str | None = None
    lesson: str | None = None
    page: int | None = None
    source_title: str
    corpus_version: str
    reviewed: bool = False
```

### 5.3 稳定 ID 与索引清单

source ID 使用内容与来源字段的稳定哈希，不再使用 `history-{sequence}`：

```text
sha256(source_title | grade | lesson | page | document_type | normalized_claim)[:24]
```

每次建索引生成 `knowledge_base/history/index_manifest.json`：

- `corpus_version`；
- 原始文档数、fact 数、chunk 数；
- embedding provider / model / dimension；
- splitter version；
- build commit、构建时间；
- 各来源等级数量；
- 校验失败与跳过数量。

### 5.4 语料处理

新增离线脚本：

- `scripts/build_history_documents.py`：标准化 corpus、拆分原子事实、导入 reviewed event facts；
- `scripts/validate_history_corpus.py`：检查 source ID、页码、实体、aspect、父引用和重复项；
- `scripts/build_history_entity_catalog.py`：生成实体与别名目录；
- 扩展 `scripts/build_pgvector_index.py`：读取标准化文档并写入 manifest。

语料规则：

- 一个 `textbook_fact` 只表达一个主要事实或一个问答维度。
- OCR 段落保留为 parent passage，但不直接作为首选答案片段。
- 原子事实长度建议 30-220 个汉字；上下文 passage 建议不超过 800 个汉字。
- 自动抽取只能生成 `reviewed=false` 的候选；进入生产 L1/L2 前必须通过规则校验和抽样人工复核。
- 对教材没有直接支持的 `geo_events` 条目只能进入 L3；争议性数字、评价和缺少来源的内容默认不入库。

---

## 6. 检索与排序设计

### 6.1 三路召回

每个通道独立返回 `source_id + rank + raw_score`：

1. **Entity channel**：按 `entity_id / canonical_name / aliases / lesson` 精确查询，实体命中优先；候选 `k=20`。
2. **BM25 channel**：使用 `retrieval_query` 搜索 claim + context，候选 `k=30`。
3. **Vector channel**：pgvector cosine 检索，候选 `k=30`。

课程上下文是 filter，实体和 aspect 默认是 ranking signal。只有用户明确指定年级/课次，或上下文来自可信教材页面时，才使用强 metadata filter，避免空 metadata 把正确文档整体过滤掉。

### 6.2 RRF

使用 Reciprocal Rank Fusion 合并三个排名：

```text
rrf_score(d) = sum(channel_weight[c] / (60 + rank_c(d)))
```

初始权重：

| 通道 | entity 已识别 | entity 未识别 |
| --- | ---: | ---: |
| entity | 1.4 | 0 |
| BM25 | 1.0 | 1.1 |
| vector | 1.0 | 1.0 |

权重只通过 reviewed eval 调整，不根据单个线上案例临时硬编码。

### 6.3 维度感知重排

RRF top 20 进入 reranker，输入必须同时包含：

```text
原始问题 + entity + aspect + 文档 claim + 父上下文摘要 + 来源等级
```

最终排序因子：

- reranker relevance；
- entity exact match；
- aspect exact/compatible match；
- source tier；
- trusted lesson/grade match；
- duplicate parent diversity。

硬约束：不同实体且没有明确关系的文档不得进入 top 4；同一 parent 最多保留两条 fact，避免一个长段落占满上下文。

### 6.4 Reranker 运行契约

`backend/rag/rerank.py` 返回结果外，还必须产生：

```json
{
  "status": "enabled|skipped|failed",
  "model": "...",
  "candidate_count": 20,
  "output_count": 6,
  "duration_ms": 123,
  "reason_code": null
}
```

生产默认不得静默降级。未配置模型可以继续走 RRF，但 diagnostics 和 AgentOps 必须记录 `rerank_status=skipped`。

---

## 7. 证据充分性与回答契约

### 7.1 三种结果状态

新增 `EvidenceSufficiency`：

| 状态 | 条件 | 用户行为 |
| --- | --- | --- |
| `sufficient` | 正确实体且至少一条来源直接支持目标 aspect | 正常回答并给出处 |
| `partial` | 实体正确，但只支持邻近维度或来源仅为 L3 | 限定范围回答，明确“教材直接信息有限” |
| `none` | 无正确实体来源、来源冲突未解决或得分低于阈值 | 不生成事实答案，提示补充课次或更换问法 |

`ToolResult.ok` 继续表示工具是否执行成功；新增：

```json
{
  "retrieval_status": "sufficient|partial|none",
  "source_count": 3,
  "answer_bearing_source_count": 1,
  "entity_match": true,
  "aspect_match": true,
  "reason_codes": []
}
```

UI 状态文案：

- 工具调用成功且 `sufficient`：`找到 3 条依据`；
- 工具调用成功但 `partial`：`找到部分相关依据`；
- 工具调用成功但 `none`：`未找到足够依据`；
- 工具异常：`检索失败`。

不得再用统一的“已完成”表达上述四种状态。

### 7.2 回答规则

- 第一优先级只使用 L1/L2 回答教材问答。
- 使用 L3 时必须写“补充资料显示”，并显示来源名称，不得伪造教材课次或页码。
- 回答关键句必须对应 source ID；generation 不能自行生成 source ID。
- `aspect=significance` 时，过程材料只能作背景，不能代替意义结论。
- `aspect=contribution` 且 entity 为人物时，后人继承、评价或时代影响不能写成人物本人行为。
- `none` 不进入正常 LLM 事实生成；直接走确定性证据不足响应。

### 7.3 与 Answer Verifier 的关系

```text
EvidenceSufficiency：生成前判断“有没有资格回答”
AnswerVerifier：生成后判断“实际回答是否被来源支持”
```

需要来源的 intent 只有同时满足以下条件才能 `completion_status=completed`：

1. `retrieval_status=sufficient`；
2. `verification.completion_allowed=true`；
3. `unsupported_critical_claim_count=0`。

`partial` 必须输出 `completion_status=partial`，不得在 UI 标记为完整解决。

---

## 8. 工具、会话与可观测性

### 8.1 `search_history_knowledge` 输入

保留旧字段兼容，新增结构化字段：

```python
class SearchHistoryKnowledgeInput(BaseModel):
    query: str
    history_query: HistoryQuery | None = None
    grade: str | None = None
    lesson: str | None = None
    topic: str | None = None  # deprecated after v1.31.2
    k: int = 6
```

Planner 在 v1.31.1 起优先传 `history_query`；旧调用没有该字段时由工具内部解析。

### 8.2 会话持久化

历史消息只持久化 UI 恢复需要的安全字段：

- `source_id`、entity、aspect、snippet/claim；
- source title、tier、grade、lesson、page；
- final rank、retrieval status；
- corpus/index version。

不持久化 embedding、完整 reranker 输入、内部 prompt、数据库字段或未脱敏长原文。

### 8.3 Diagnostics

`RetrievalDiagnostics` 进入 Langfuse span 和 AgentOps 聚合，但前端默认只显示面向学生的来源摘要：

- query parser mode / confidence；
- 各通道候选数与耗时；
- RRF top IDs；
- reranker status / model / latency；
- entity/aspect match；
- sufficiency status / reason codes；
- corpus/index version；
- total retrieval latency。

开发者调试区可以查看 diagnostics，不得在普通学生回答中展示内部打分。

---

## 9. 评测设计

### 9.1 数据集

新增：

- `eval/datasets/history_query_cases.json`：实体、aspect、上下文继承和澄清，至少 120 条；
- `eval/datasets/history_retrieval_cases.json`：相关性分级、answer-bearing source，至少 120 条；
- `eval/datasets/history_no_answer_cases.json`：教材无直接依据、相似实体和干扰问法，至少 40 条；
- `eval/datasets/history_answer_grounding_cases.json`：关键 claim 与来源映射，至少 60 条。

每个高频事件至少覆盖：

```text
是什么 / 原因 / 经过 / 结果 / 影响 / 意义 / 评价
直接问法 / 口语改写 / 省略主语 / 多轮追问
正确年级 / 无年级 / 错误课程干扰
有答案 / 只有部分答案 / 无答案
```

首批必须包含：长平之战、赤壁之战、鸦片战争、洋务运动、商鞅变法、苏轼、辛弃疾、贞观之治、张骞出使西域、虎门销烟。

### 9.2 相关性标注

每个 query-source 标注：

- `0`：无关或错误实体；
- `1`：实体相关但不能回答目标 aspect；
- `2`：可直接支持目标 aspect。

answer-bearing Recall、nDCG 和 MRR 只能按 reviewed 标签计算，不能用“包含关键词”代替。

### 9.3 新增评测脚本

- `eval/history_query_eval.py`；
- `eval/history_retrieval_quality_eval.py`；
- `eval/history_no_answer_eval.py`；
- `eval/history_answer_grounding_eval.py`；
- 保留 `eval/history_search_relevance_smoke.py` 作为快速确定性回归。

### 9.4 发布门禁分层

| Profile | 内容 | 运行条件 |
| --- | --- | --- |
| fast | parser、固定候选 RRF、sufficiency、UI contract | 每次提交 |
| core | reviewed 检索集、grounding、现有学习助手轨迹 | PR / main |
| production | 真 pgvector、真实 embedding、真实 reranker、延迟 | 发布前 |

生产评测若缺少数据库、embedding 或 reranker，不得记为通过；应显示 `not_run` 并阻止检索版本盖章。

---

## 10. 实施阶段

### Phase 0：基线冻结与失败集（v1.31.0）

1. 固化当前 commit、语料 hash、索引配置和线上失败样本。
2. 建立 `HistoryQuery` 和四类 reviewed 数据集。
3. 将现有 `rag_retrieval_eval` 从关键词命中升级为分级相关性指标。
4. 在不改变生产排序的情况下记录 entity/aspect 与 diagnostics shadow。

退出条件：查询解析集和检索集完成双人抽样复核；当前排序有可重复 baseline。

### Phase 1：结构化查询与 RRF（v1.31.1）

1. 引入实体目录和 deterministic-first query parser。
2. 将三个召回通道拆分为独立 ranked lists。
3. 上线 RRF，保留旧融合策略 feature flag 作为回滚路径。
4. 将 reranker 状态显式写入 diagnostics。

Feature flags：

```text
EDU_AGENT_HISTORY_QUERY_V2_ENABLED
EDU_AGENT_HISTORY_RRF_ENABLED
EDU_AGENT_HISTORY_RERANK_ENABLED
```

退出条件：reviewed 集达到第 3 节检索门槛，fast/core gate 全绿。

### Phase 2：语料工程与来源分层（v1.31.1）

1. 建立稳定 source ID、parent-child 文档和 index manifest。
2. 优先治理评测覆盖的高频事件/人物，再扩展全量教材。
3. 将通过来源审核的 `geo_events` 条目以 L3 导入；未审条目继续隔离。
4. 完成新旧索引双写构建和离线对比，不在请求路径实时重建索引。

退出条件：所有评测命中的 source ID 稳定；L1/L2/L3 展示无混淆；语料校验 100% 通过。

### Phase 3：证据门控与 UI（v1.31.2）

1. 增加 sufficiency gate 与 `sufficient/partial/none`。
2. 调整 completion status、工具卡文案和刷新恢复字段。
3. 将 sufficiency 与 Answer Verifier 串成双门控。
4. 增加无答案和弱证据回归。

退出条件：no-evidence completed rate 为 0；重复卡、空卡和刷新丢来源均有测试覆盖。

### Phase 4：灰度与盖章

```text
shadow 100%（只记录）
  -> 10% 学生流量
  -> 50% 学生流量
  -> 100%
```

每阶段至少满足：

- 样本量分别 `200 / 500 / 1000`；
- “解决了”率不低于旧策略；
- “换种方式讲/重新生成”率不高于旧策略 2 个百分点；
- unsupported critical claim rate 不高于 2%；
- p95 不超过门槛；
- 任一错误实体回答、L3 冒充教材或 no-evidence completed 立即回滚。

---

## 11. 代码改动清单

### 后端

- `backend/rag/history_query.py`：查询结构与解析。
- `backend/rag/history_documents.py`：标准文档与来源等级。
- `backend/rag/knowledge_base.py`：独立通道、RRF、diagnostics。
- `backend/rag/rerank.py`：显式状态与维度感知输入。
- `backend/tools/history_search.py`：新输入输出与 sufficiency。
- `backend/agents/learning_assistant_planner.py`：传递 `HistoryQuery`。
- `backend/agents/learning_assistant.py`：按 sufficiency 生成或拒答。
- `backend/agents/answer_verifier.py`：接收来源等级和 retrieval status。
- `backend/services/learning_assistant_session_service.py`：持久化安全来源字段。

### 数据与脚本

- `knowledge_base/history/entities.json`。
- `knowledge_base/history/index_manifest.json`。
- `scripts/build_history_entity_catalog.py`。
- `scripts/build_history_documents.py`。
- `scripts/validate_history_corpus.py`。
- `scripts/build_pgvector_index.py`。

### 前端

- `frontend/app/learning-assistant/page.tsx`：工具卡证据状态和来源等级。
- `frontend/components/learningAssistantComposer.ts`：保持 tool repair 去重。

### 评测

- 第 9 节四个数据集和四个 eval。
- `eval/run_core_evals.py`：注册 fast/core/production profile。
- `scripts/release_gate.py`：生产检索盖章与 not_run 阻断。

---

## 12. 风险与回滚

| 风险 | 控制措施 | 回滚信号 |
| --- | --- | --- |
| 实体目录漏词导致召回下降 | BM25/vector 保底，LLM 只能选候选 | entity Recall@5 下降 > 2% |
| 强 metadata filter 误杀 | 仅可信 scope 使用强 filter | source_count=0 异常升高 |
| reranker 延迟或不可用 | RRF 可独立服务，显式 skipped | rerank p95 > 350ms 或失败率 > 1% |
| L3 补充资料污染教材回答 | 来源等级硬约束与 UI 标签 | 任一 L3 冒充教材 |
| 原子事实抽取引入错误 | parent citation、reviewed 标记、抽样复核 | unsupported claim > 2% |
| 新索引构建失败 | 新旧 collection 并存，原子别名切换 | health check 或 production eval 失败 |

回滚粒度：

1. 关闭 sufficiency/UI 新状态；
2. 关闭 reranker；
3. 关闭 RRF，回到旧 hybrid；
4. 关闭 Query V2；
5. 数据层将 collection alias 切回上一 index manifest。

---

## 13. 验收清单

### 功能

- [ ] `长平之战的意义` 解析为正确 entity/aspect。
- [ ] 教材只提到长平之战但没有意义结论时返回 partial，不编造完整教材答案。
- [ ] reviewed L3 可作为明确标注的补充资料，不显示教材页码。
- [ ] `苏轼做了什么` 不把辛弃疾的行为写成苏轼贡献。
- [ ] “结合教材解释”能够继承上一轮可信实体。
- [ ] 无关史料不会占据 top 3。
- [ ] 刷新后来源、状态和出处仍可见。
- [ ] repair 后同一工具只显示最终结果。

### 质量

- [ ] 第 3 节查询、检索、回答指标全部达标。
- [ ] `no-evidence completed rate=0`。
- [ ] 所有引用 source ID 可在当前 index manifest 解析。
- [ ] production profile 使用真实 pgvector、embedding 和 reranker 完成盖章。

### 工程

- [ ] fast release gate 全绿。
- [ ] core eval 无 skipped / not_run 阻断项。
- [ ] 新旧排序 feature flag 可独立回滚。
- [ ] 数据库与语料迁移不要求请求路径停机重建。
- [ ] AgentOps 能按 index version、query parser mode、retrieval status 和 rerank status 聚合。

---

## 14. 推荐实施顺序

本项目当前最高杠杆顺序是：

1. 先建立 reviewed 失败集和 `HistoryQuery`，避免继续用单案例补正则。
2. 再把现有 hybrid 改成可解释的独立通道 + RRF，并让 reranker 可观测。
3. 只治理评测命中的高频教材语料，建立 parent-child 和来源等级。
4. 最后启用 sufficiency 双门控和 UI 状态，再进入灰度。

不建议先做 GraphRAG、全量自动知识抽取或更换 embedding 模型。没有稳定相关性标签与证据状态时，这些投入无法证明改善，也会扩大调试面。

---

## 15. 实施记录（2026-08-14）

已完成：

- `HistoryQuery`、实体目录、确定性实体/aspect 解析和上下文继承；
- entity / BM25 / vector 独立召回、RRF、可观测 reranker；
- `HistorySource`、稳定 source ID、三层来源与 parent-child 文档构建；
- `sufficient / partial / none` 证据充分性和 Answer Verifier 双门控；
- Planner、Runtime、会话恢复、AgentOps 元数据和前端工具卡状态接入；
- “分析/分析下/分析一下”等命令式问法稳定进入历史检索，并从主题中剥离命令前缀；
- 针对原因、经过、结果、影响、意义等 aspect 抽取最小可作答证据，生成阶段仅使用 answer-bearing sources；
- 相同证据片段去重，避免教材正文、OCR 长段和练习题重复污染回答；
- 语料构建、语料校验、稳定索引 ID 和 index manifest 构建逻辑；
- 120 条查询解析种子、120 条检索种子、40 条无答案种子、60 条 grounding 种子；
- fast release gate 新增 query、RRF/sufficiency、no-answer 和 grounding suites。
- 人工相关性复核工作流：按当前检索版本导出稳定 source ID 候选快照，教研填写 `0/1/2` 判断后先 dry-run 校验，再显式 `--write` 原子写回；禁止 `system/auto/llm` 作为 reviewer。
- 生产检索评测不再用系统自身的 `entity_match / answer_bearing` 充当相关性标签；Recall、MRR、nDCG 只读取 `teacher_reviewed` 的 source judgments，当前 top source 出现未标注 ID 时返回 `NOT_RUN`。
- 查询种子按 `event / person` 实体类型生成：苏轼、辛弃疾不再套用“为什么会发生某人”等事件模板；数据集重建只保留指纹未变化的既有人工复核，变更 case 自动回到 pending。
- 本地无向量库时，aspect 明确且教材证据不足的事件查询可补充 `geo_events.json` 的 L3 稳定来源；L3 只产生 `partial`，不会冒充 L1/L2 教材充分证据，精确名单、私人谈话和逐日路线等超范围问题仍返回 `none`。
- “中国历史以少胜多的战役有哪些”等跨事件集合问法不再把整句误当单一实体；系统先用受控事件目录确定候选集合，再只从教材正文中提取明确写有“以少胜多”的 L1 直接证据，并按来源拆分验证 claim。当前覆盖巨鹿之战、官渡之战、赤壁之战和淝水之战，完整链路返回 `sufficient / verified / completed`。

当前工程验证：

- history query：`120/120`；
- history no-answer：`40/40`；
- history grounding：`60/60`；
- history retrieval review contract：`11/11`；
- fast release gate：`25/25 suites`、`508/508 cases`；
- full core eval：`40/40 suites`、`593/593 cases`；
- 前端相关单测：`7/7`；
- Next.js production build：通过。

专项回归：

- `分析下官渡之战`：直接进入 `history_search`，实体归一为“官渡之战”，不再要求用户重复澄清；
- `分析下官渡之战的意义`：只使用“迅速歼灭袁军主力，为以后统一北方打下基础”作为直接依据，不把挟天子、屯田或声东击西等背景和经过写成意义；
- 上述场景已进入 `history_search_relevance_smoke.py` 和 `learning_assistant_multiturn_smoke.py`。

发布前仍需完成：

1. 教研人员使用 `npm run history:review -- export ...` 导出候选快照，为每个 query-source 标注 `0/1/2`，并通过 dry-run 后显式写回；截至 2026-08-17，本轮人工复核已写回，状态为 `117/120 teacher_reviewed`、`3/120 teacher_rejected`、`0 pending`。剩余 3 条均为长平之战原因/经过缺少直接资料；补齐证据并重新复核前，生产检索质量 gate 继续阻断盖章。
2. 使用真实 `DATABASE_URL + EMBED_API + RERANK_MODEL_PATH` 重建 history collection；构建完成后生成 `index_manifest.json`。
3. 运行 `release:gate:prod`，确认真实 entity/aspect Recall、MRR、nDCG 与延迟达到第 3 节门槛。
4. 按 Phase 4 收集 shadow / 10% / 50% / 100% 生产样本；代码完成不能替代灰度证据。
