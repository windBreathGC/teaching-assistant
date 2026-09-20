# 中学伴学助教 - 后端

FastAPI 后端服务，提供教材检索（RAG）、AI 对话、随堂测验、作答判分、学情画像等 API。

> 项目整体介绍、安装与启动方式见根目录 [README.md](../README.md)。本文档收录后端的**设计与实现细节**：流式接口（SSE）契约、知识检索（混合检索 + RRF 融合 + 充分性判定）、LangGraph 对话工作流（含 checkpointer 多轮记忆）、测验判分闭环、学习者画像、韧性设计（重试/降级/熔断/限流）、向量化增量更新机制、Langfuse 可观测性接入与自托管部署。

## 流式响应设计（SSE）

### 概述

对话与出题各有一对接口：非流式返回完整 JSON，流式通过 SSE 逐 token 推送；作答判分为独立接口（非流式，判分结果较短无需流式）。

| 接口 | 方式 | 说明 |
|------|------|------|
| `POST /chat` | 普通 JSON | 一次性返回完整回复（含 `session_id`、`references`） |
| `POST /chat/stream` | SSE | 意图识别 → 教材出处 → 逐 token 生成 → 收尾汇总 |
| `POST /chat/quiz` | 普通 JSON | 一次性返回完整题目（含 `quiz_id`） |
| `POST /chat/quiz/stream` | SSE | 逐 token 生成题目 → 解析后收尾（含 `quiz_id`） |
| `POST /chat/quiz/submit` | 普通 JSON | 提交答案判分：判分 + 错因诊断 + 掌握度更新（幂等） |

### 传输格式（SSE 协议强制部分）

SSE（Server-Sent Events）规范只约束**传输封装**，不约束业务内容：

- 响应头必须是 `Content-Type: text/event-stream`（`StreamingResponse(..., media_type="text/event-stream")`）
- 每个事件以 `data: <内容>` 开头、以**两个换行符 `\n\n`** 结尾——这是 SSE 解析事件边界的唯一依据
- 连接为单向长连接：服务器持续推送，全部发完后关闭

### 应用层事件协议（本项目自定义约定）

`data:` 后面的内容是一个**单行 JSON 对象**，通过 `type` 字段区分事件类型。这套结构不是 SSE 规范要求的，而是本项目前后端双方约定好的应用层协议，前端按同样的约定解析（`frontend/src/api/client.ts` 的 `sendStream` / `generateStream`）。

#### `POST /chat/stream` 事件序列

```
data: {"type": "intent", "intent": "知识问答"}

data: {"type": "references", "references": [{"lesson": "...", "chapter": "..."}], "retrieval_ok": true}

data: {"type": "token", "content": "这"}
data: {"type": "token", "content": "道"}
data: {"type": "token", "content": "题"}
...（逐 token 推送，数量不定）

data: {"type": "done", "reply": "完整回复全文", "suggested_actions": ["出道例题", "总结重点"], "references": [...], "retrieval_ok": true, "session_id": "abc123..."}
```

| 事件 | 时机 | 字段 | 说明 |
|------|------|------|------|
| `intent` | 流开始，仅一次 | `intent` | 意图识别结果（知识问答 / 课程讲解 / 测验请求 / 作答判分 / 进度查询 / 自由聊天） |
| `references` | 检索完成，仅一次（仅知识问答/课程讲解/测验请求路径有） | `references`、`retrieval_ok` | 教材出处列表与检索充分性，前端可提前展示出处；`retrieval_ok=false` 表示未在教材中找到足够依据，AI 会明确告知而非强行作答 |
| `token` | 生成中，零到多次 | `content` | 一个增量文本片段，前端按序拼接即为完整回复 |
| `done` | 正常结束，仅一次 | `reply`、`suggested_actions`、`references`、`retrieval_ok`、`session_id` | `reply` 为完整回复全文（与全部 token 拼接结果一致）；`session_id` 为多轮记忆的会话 ID，前端需持久化并在后续请求中回传 |
| `error` | 任何阶段异常时 | `detail` | 用户可读的错误提示；发送后连接结束 |

#### `POST /chat/quiz/stream` 事件序列

```
data: {"type": "token", "content": "【"}
...（逐 token 推送题目原文）

data: {"type": "done", "question": "...", "options": ["A. ...", "B. ..."], "correct_answer": "A", "explanation": "...", "knowledge_point": "...", "quiz_id": "..."}
```

| 事件 | 时机 | 字段 | 说明 |
|------|------|------|------|
| `token` | 生成中，零到多次 | `content` | 题目原文的增量片段 |
| `done` | 正常结束，仅一次 | `question`、`options`、`correct_answer`、`explanation`、`knowledge_point`、`quiz_id` | 后端将全部 token 拼接后经 `parse_quiz_output` 解析出的结构化题目；`options` 仅选择题有值；`quiz_id` 为出题落库 ID，提交答案判分时凭它关联 |
| `error` | 任何阶段异常时 | `detail` | 同上 |

#### `POST /chat/quiz/submit` 判分接口

```
请求: {"quiz_id": "aaf81d...", "user_answer": "我选B"}

响应: {
  "quiz_id": "aaf81d...",
  "is_correct": false,
  "correct_answer": "C",
  "explanation": "...",
  "diagnosis": "你选择了B，说明……但题目问的是……",   // AI 错因诊断
  "misconception": "审题偏差",                          // 错因标签
  "knowledge_point": "寓言的寓意",
  "mastery": {"knowledge_point": "寓言的寓意", "mastery": 0.0, "total_attempts": 1, "correct_attempts": 0}
}
```

判分是**幂等**的：同一 `quiz_id` 重复提交直接返回首次判分结果，不会重复累计掌握度（实现见「测验判分闭环」一节）。

### 设计要点

- **`done` 携带完整全文是刻意的冗余**：`token` 事件让 UI 实时渲染，`done` 的 `reply`/`question` 让前端可以用服务端权威结果**覆盖**本地拼接结果，避免中间丢包或解析误差导致最终文本不一致。
- **错误也通过事件下发而非中断连接**：一旦响应头已发出（流已开始），HTTP 状态码就无法再改，因此生成过程中的异常只能以 `error` 事件的形式告知前端。前端收到 `error` 后应停止等待并提示用户。
- **正常结束以 `done` 事件为界**，而非连接关闭：前端收到 `done` 即认为本次流结束；连接随后由后端关闭。

### 前端消费方式

浏览器原生 `EventSource` 只支持 GET，而这两个接口是 POST，因此前端用 `fetch` + `ReadableStream` 手动解析：

```
fetch(POST) → response.body.getReader()
  → 循环 read()，按 \n 切分缓冲
  → 行首为 "data: " 时 JSON.parse 剩余部分
  → 按 payload.type 分发：token → onToken / references → onReferences / done → onDone / error → onError
```

### 修改协议时的注意事项

1. **前后端必须同步修改**：事件类型名、字段名的任何改动都要同时改 `backend/app/api/chat.py` 和 `frontend/src/api/client.ts`，否则前端解析失败。
2. **未知事件类型会被前端忽略**：当前 `intent` 事件即属此类——后端发送，前端暂未使用（仅处理 `references`/`token`/`done`/`error`）。新增事件类型时，未升级的旧前端会静默跳过，这可以作为平滑升级的利用点（`references` 事件即按此原则新增）。
3. **每个事件必须是单行 JSON**：SSE 以换行划分事件，JSON 内不能出现裸换行（`json.dumps` 默认满足，不要手动拼接多行文本）。

## 知识检索：混合检索与 RRF 融合

检索采用**三级策略：metadata 精确匹配优先，未指定课文时走「向量 + BM25」混合检索，RRF 融合排序**。实现在 `app/services/rag.py`（入口 `retrieve`/`aretrieve`，混合检索 `_hybrid_retrieve`，融合 `_rrf_merge`）。

### 整体流程（三级策略）

```
用户提问
   │
   ├─ 意图识别（classify_intent）：知识问答 / 课程讲解 → 进入检索
   ▼
年级/学期推导：从学科 ID 后缀补齐过滤条件
   （如 chinese_7b → grade=七年级, semester=下册，避免跨年级内容混排）
   │
   ├─ 指定了课文 → metadata 精确匹配（_get_doc_by_lesson_name）：
   │     collection.get(where={subject, grade, semester}) 取出该册 chunk，
   │     按 lesson 字段子串匹配，命中即返回（distance=0）
   │     兜底：正文含《课文名》的 chunk，按 #### 子标题截取（适用于古诗词等子课文）
   │
   └─ 未指定课文 → 混合检索（hybrid retrieval）：
         ├─ 向量路：embed(query) → collection.query(where, n_results=fetch_k=20)
         ├─ 关键词路：BM25（bm25s）在同一 where 范围内召回 top 20
         │     分词：中文按 单字+二元组、英文/数字按整词（对齐 ES CJK analyzer）
         ├─ RRF 融合：只按两路排名打分（1/(60+rank)），避开分数量纲差异
         └─ 截断到 top_k 返回
   ▼
检索结果注入 Prompt → LLM 流式生成
```

- 两路操作的是**同一份 ChromaDB 数据**：向量路用记录的 `embeddings` 字段算相似度，BM25 路把满足过滤条件的 `documents` 原文捞出后在内存临时建词项索引（按 where 条件缓存，入库后失效）。
- 指定课文时走精确匹配短路的原因：长文本 embedding 会被稀释，metadata 精确匹配比向量检索更可靠。
- BM25 召回为空或失败时自动降级为纯向量检索，不影响主链路。

### RRF 算法定义

RRF（Reciprocal Rank Fusion，倒数排名融合）：对每篇文档 d，把它在**每一路**检索结果中的名次贡献**累加**：

```
RRF_score(d) = Σ  1 / (k + rank_r(d))        k = 60（惯例平滑常数）
              r∈检索器集合
```

三个要素：逐路求和（Σ）；每路贡献只取决于名次 rank，与原始分数无关；k 压制头部名次的权重差异。

之所以不看原始分数：向量距离（越小越好）与 BM25 分数（越大越好）量纲不同、不可比，无法直接加权；名次则天然可比（第 3 名就是第 3 名），因此 RRF 几乎免调参。


### 代码实现（`rag.py` `_rrf_merge`）

```python
def _rrf_merge(vector_hits, bm25_hits, k=60):
    scores, docs = {}, {}
    for hits in (vector_hits, bm25_hits):        # 外层循环 = 公式中的 Σ（遍历两路）
        for rank, hit in enumerate(hits):        # 输入已有序，enumerate 下标即名次（0 起）
            key = hit.get("id") or hit["content"][:64]   # 跨路对齐"同一篇文档"的身份标识
            docs.setdefault(key, hit)            # 登记文档本体（只需一次）
            scores[key] = scores.get(key, 0.0) + 1 / (k + rank + 1)  # 累加 1/(k+rank)
    return [docs[key] for key in sorted(scores, key=scores.get, reverse=True)]
```

代码与公式的逐行对应：

| 代码 | 公式要素 |
|------|----------|
| 外层 `for hits in (vector_hits, bm25_hits)` | Σ：同一文档在两路各命中一次就累加两次，**累加而非赋值**是 Σ 的体现 |
| `enumerate(hits)` | 两路输入已各自有序（距离升序 / 分数降序），下标天然是名次，无需再排序 |
| `rank + 1` | `enumerate` 从 0 起，公式名次从 1 起，+1 对齐 |
| `key = id or content[:64]` | 两次独立查询返回不同 dict 对象，靠 ChromaDB id（无 id 时用内容指纹兜底）认出同一篇，否则 Σ 无从谈起 |
| `docs.setdefault` | 顺带建立 key → 文档映射，供排序后取回内容 |
| 末行 `sorted(..., reverse=True)` | 按融合总分降序输出 |

### 计算示例

```
vector_hits = [A, B, C]     # 向量路：A 最相似
bm25_hits   = [B, D, A]     # BM25 路：B 分最高

向量路：
  A: rank=0 → scores[A] = 0 + 1/61 = 0.016
  B: rank=1 → scores[B] = 0 + 1/62 = 0.01613
  C: rank=2 → scores[C] = 0 + 1/63 = 0.01587

BM25 路（同一批 key 继续累加）：
  B: rank=0 → scores[B] = 0.01613 + 1/61 = 0.03252   ← 两路都命中，分数翻倍级
  D: rank=1 → scores[D] = 0 + 1/62     = 0.13
  A: rank=2 → scores[A] = 0.01639 + 1/63 = 0.03226

排序结果：B (0.03252) > A (0.03226) > D (0.01613) > C (0.01587)
```

结果体现了 RRF 的两个关键性质：

- **两路都命中的文档（B、A）得分约为单路命中者的两倍**，稳居前二——两路投票胜过单路冠军；
- **B 反超 A**：A 在向量路第 1 但 BM25 路仅第 3，B 两路都靠前（第 2、第 1）——融合偏爱"两路都认可"而非"一路偏科"的文档。

### 设计取舍

| 设计 | 说明 |
|------|------|
| 双路召回 | 向量路擅长语义泛化（"讲讲这首诗的情感"），BM25 路擅长精确匹配（课文名、术语、专名），互补短板 |
| RRF 不加权、不归一化 | 两路通常没有先验理由分出权重；k=60 使第 1 名（1/61）与第 5 名（1/65）得分相差无几，单路高名次无法独裁结果 |
| 召回/返回分层 | 每路召回 `fetch_k=20` 条（宁多勿漏），融合后截断到 `top_k`（调用方传入，默认 5） |
| n-gram 分词 | 不依赖词典、不怕未登录词，且无需引入已停更的中文分词库 |
| BM25 索引缓存 | 索引按 where 过滤条件缓存在内存（`keyword_search.py`），教材入库/删除后自动失效重建，**无需重启服务** |
| 降级 | BM25 索引构建/检索失败时自动降级为纯向量检索，不影响主链路 |

### 检索充分性判定与引用溯源

对话工作流使用的入口是 `aretrieve_checked`（`rag.py`），在混合检索之上增加两个能力：

```python
async def aretrieve_checked(query, subject=None, lesson=None, top_k=5, fetch_k=20) -> dict:
    """返回 {"docs": [...], "sufficient": bool}"""
    # 指定课文走 metadata 精确匹配（distance=0）→ sufficient=True
    # 混合检索 → 以向量路 top1 距离是否越过阈值判定 sufficient
```

**1. 充分性判定（防强行作答）**

```python
def _judge_sufficiency(vector_hits: list[dict]) -> bool:
    distances = [d["distance"] for d in vector_hits if d.get("distance") is not None]
    top1 = min(distances) if distances else None
    sufficient = top1 is not None and top1 <= settings.RAG_DISTANCE_THRESHOLD
    logger.info("检索充分性: top1_distance=%s threshold=%.2f sufficient=%s", ...)
    return sufficient
```

三个要点：

- **判定必须在向量召回阶段（RRF 融合前）**：融合后 BM25-only 命中没有 distance，无法在融合结果上统一判断。
- **阈值是 l2 距离**（collection 默认 `hnsw:space=l2`），`RAG_DISTANCE_THRESHOLD` 默认 1.2、可在 `.env` 调整。不同 embedding 模型的距离分布不同，调参依据是上面这行 INFO 日志里的 `top1_distance`（语文教材实测相关命中约 0.55~0.68）。
- **`sufficient=false` 时不丢弃检索结果**，而是在 reply 的 prompt 后拼接 `_FALLBACK_NOTE`，引导模型明确告知"教材中暂未找到直接依据"、再基于通用知识简要回答并建议换问法——把"强行作答的幻觉"变成"诚实的兜底"。

**2. 引用溯源（references）**

`citations.to_references(docs)` 把检索结果投影为前端引用卡片（纯函数）：

```python
def to_references(docs: list[dict], max_snippet: int = 120) -> list[dict]:
    """[{lesson, chapter, subject, grade, semester, snippet, score?}]
    - 按 lesson 去重，避免同一课文多个 chunk 刷屏
    - distance 为 None（BM25-only 命中）时省略 score，前端弱化显示"""
```

数据流：`retrieve` 节点产出 `references` 写入 state → SSE 在检索完成时先下发 `references` 事件（前端可提前展示出处）→ `done` 事件再携带一次（权威结果）。

### 调用入口

| 入口 | 位置 | 说明 |
|------|------|------|
| `POST /chat/stream` | `api/chat.py` | 意图识别 → 检索（充分性判定）→ 流式生成 |
| `POST /chat` | `api/chat.py` | LangGraph：intent → retrieve → reply/quiz（见下节） |
| `POST /quiz[/stream]` | `api/chat.py` | top_k=2 检索后出题 |
| `GET /subjects/{id}/lessons/{id}/content` | `api/subjects.py` | 课文原文（metadata 精确匹配） |

### 检索侧特别提醒

1. **一键全量更新 / ingest 后请重启后端服务。** 课文 ID → 课文名的映射表（`_LESSON_NAME_MAP`）在后端启动时从 `generated/*.json` 构建一次；不重启则新增/改名的课文走不到精确匹配，会静默降级为混合检索，表现为"选了课文但回答不聚焦"。（BM25 索引缓存会自动失效重建，不受此限制。）
2. **充分性阈值需要按 embedding 模型调参。** `RAG_DISTANCE_THRESHOLD` 过严会导致大量兜底提示（学生问什么都说"教材未找到"），过松则形同虚设（无关问题也强行作答）。调整检索策略后，结合 INFO 日志的 `top1_distance` 分布与 Ragas 评估一起验证。

## LangGraph 工作流

`POST /chat` 与 `POST /chat/stream` 共用同一个 LangGraph 编排的智能体工作流（`app/services/agent.py`）：意图识别后按条件路由到不同分支，状态（`AgentState`）在节点间流转，携带消息历史、学科/课文上下文、检索结果与待作答题目。

```
                ┌──────────┐
                │  intent  │  意图识别 classify_intent
                └────┬─────┘
                     │ route_by_intent（条件路由）
        ┌────────────┼────────────┬───────────┐
        ▼            ▼            ▼           ▼
  ┌───────────┐ ┌─────────┐ ┌──────────┐ ┌─────────┐
  │ retrieve  │ │  grade  │ │ progress │ │  chat   │
  │ RAG 检索   │ │ 作答判分 │ │ 学情报告  │ │ 自由聊天 │
  │ +充分性判定│ └────┬────┘ └────┬─────┘ └────┬────┘
  └─────┬─────┘      │           │            │
        │ route_after_retrieve   │            │
        ├────────────┐           │            │
        ▼            ▼           │            │
  ┌───────────┐ ┌─────────┐      │            │
  │   reply   │ │  quiz   │      │            │
  │ 生成教学回复│ │ 检索出题 │      │            │
  └─────┬─────┘ └────┬────┘      │            │
        ▼            ▼           ▼            ▼
                     ┌──────────┐
                     │   END    │
                     └──────────┘
```

| 节点 | 说明 |
|------|------|
| `intent` | 对最后一条用户消息做意图分类：知识问答 / 课程讲解 / 测验请求 / 作答判分 / 进度查询 / 自由聊天 |
| `retrieve` | 意图为知识问答/课程讲解/测验请求时进入：课文名拼入 query，走混合检索（`top_k=2`）+ 充分性判定 + 引用溯源。**测验也先走检索——出题必须基于教材内容，不能脱离课文自由发挥** |
| `reply` | 检索结果 + 多轮历史注入 Prompt，LLM 生成教学回复与建议动作；检索不充分时拼接兜底提示 |
| `quiz` | 基于检索结果生成选择题，**出题即落库**（`quiz_attempts`，返回 `quiz_id` 写入 state，跨轮存活） |
| `grade` | 意图为作答判分（"我选B"）：从 state 取待作答 `quiz_id` → 判分 + 错因诊断 → 更新掌握度 |
| `progress` | 意图为进度查询：聚合学习数据 → LLM 包装成教师口吻的学情报告（模板兜底，真流式） |
| `chat` | 其他意图：返回引导性欢迎语，不调用 LLM |

**路由设计的关键点**：

- `route_after_retrieve`：检索后按意图分流——测验意图去 `quiz`，其余去 `reply`。这让聊天内"出道题考考我"出的题真实来自教材检索结果。
- 意图识别的两个工程细节（`intent.py`）：**作答判分走显式正则**（单字母 `A`/`b`，或"我选A/答案是B"模式，避免"我选哪篇课文""这道题的答案是什么"误伤）；**进度查询关键词用强信号**（"进度/掌握度/学情"，不用"掌握/统计/报告"这类学科内容词）。

### 对话记忆：Checkpointer 多轮会话

工作流通过 `build_agent(checkpointer)` 工厂装配，传入 `AsyncSqliteSaver` 即开启**会话级持久化记忆**（`services/memory.py`）：

```python
# services/agent.py
def build_agent(checkpointer=None):
    builder = StateGraph(AgentState)
    # ... 添加节点与边 ...
    return builder.compile(checkpointer=checkpointer)

# main.py lifespan：checkpointer 连接生命周期与 app 一致，必须在 async with 中持有
async with create_checkpointer() as checkpointer:
    app.state.agent = build_agent(checkpointer)
    yield
```

**记忆的三层设计**：

| 层 | 机制 | 说明 |
|----|------|------|
| 会话标识 | 前端 `localStorage` 的 `session_id` → 后端 `thread_id` | 每个请求携带，后端按它续接会话；为空则新建并在 `done` 事件回传。**切换课程时前端清空 session_id 开新会话**，避免跨课程上下文串味 |
| 状态续接 | `AgentState.messages` 用 `add_messages` reducer | 每轮输入只放本轮新消息，checkpointer 自动拼接完整历史（含 AI 回复）；`quiz_result` 也随之跨轮存活——这是"我选B"作答判分的前提 |
| 提示窗口 | `trim_messages` 裁剪最近 12 条发给 LLM | 只控制 prompt token，不影响 checkpointer 中的完整会话 |

**每轮输入状态的字段重置**（`api/chat.py` `_initial_state`）是个容易踩坑的点：

```python
state = {
    "messages": [HumanMessage(content=request.message)],
    "intent": "自由聊天", "retrieved_docs": [], "references": [],
    "retrieval_ok": True, "reply": "", "suggested_actions": [],
    "grade_result": None, "progress_report": None,   # 每轮重置，防陈旧值残留
    # quiz_result 故意不传 → 待作答题目跨轮存活
}
if request.subject is not None:                      # None 时沿用 checkpoint 旧值，
    state["subject"] = request.subject               # 不覆盖成 None 污染后续轮次
```

LangGraph 对 checkpointer 状态的合并语义是"输入里出现的键覆盖、未出现的键保留"，所以：**会被本轮覆盖的字段显式重置防脏数据，需要跨轮的字段（quiz_result）刻意不传，可选上下文字段（subject/chapter/lesson）空值时不传以沿用旧值**。

**流式接口如何复用该图**：`POST /chat/stream` 通过 `agent.astream_events(version="v2", config={"configurable": {"thread_id": session_id}})` 消费同一个工作流，把图内事件映射为 SSE 事件：

| 图事件（astream_events） | SSE 事件 | 说明 |
|------|------|------|
| `intent` 节点 `on_chain_end` | `intent` | 意图识别结果 |
| `retrieve` 节点 `on_chain_end` | `references` | 教材出处 + 检索充分性 |
| `reply`/`progress` 节点内 LLM 的 `on_chat_model_stream` | `token` | 真流式的关键：这两个节点内部用 `chain.astream` 逐 token 聚合，token 事件才能冒泡出图 |
| `quiz` / `grade` / `chat` 节点 `on_chain_end` | `token`（一次性全文） | 这三个分支无 LLM 流（grade 的判文是组装好的），节点完成后整体下发 |
| 终态节点 `on_chain_end` | `done` | `reply`/`suggested_actions` 取节点输出的权威结果，而非前端拼接 |

注意：节点内子链（prompt\|llm 等）会继承 `langgraph_node` 元数据，过滤节点级事件时必须同时匹配 `event == "on_chain_end"` 且 `name == langgraph_node`，否则会把子链输出误判为节点结果。

### `astream_events` 的语义：调用即执行

一个容易误解的点：`agent.astream_events(initial_state, version="v2", config=config)`（`api/chat.py`）**不是单纯的"监听"方法，而是一次完整的图执行**。调用它时会用 `initial_state` 作为输入更新（checkpointer 按 `config` 里的 `thread_id` 续接历史），从入口节点 `intent` 开始把整张工作流跑完（intent → 路由 → retrieve → reply/quiz，或 grade/progress/chat → END），并在执行过程中把每个节点/子链/LLM 触发的回调事件（`on_chain_start`、`on_chat_model_stream`、`on_chain_end` 等）逐个 yield 出来。

它与非流式的 `agent.ainvoke(...)` 执行的是**同一个编译后的图**，区别仅在于产出形式：

| | `ainvoke` | `astream_events` |
|---|---|---|
| 是否执行工作流 | 是 | 是 |
| 返回值 | 最终 state（一次性） | 过程事件流（逐个 yield） |
| 拿到最终结果 | `result["reply"]` | 需从终态节点的 `on_chain_end` 事件里取 |

由此带来两个实现约束：

1. **事件流结束 = 图执行完毕。** `async for` 循环退出即代表整张图跑完，此时才发 `done` 事件。代码里用 `on_chain_end` + `name == langgraph_node` 判断节点完成、用 `on_chat_model_stream` 捕获 reply 节点的逐 token 输出，都是把"事件流当作图执行过程的实时回放"来消费的。
2. **`astream_events` 不直接返回最终 state。** 最终 `reply`/`suggested_actions` 必须从终态节点（reply/quiz/grade/progress/chat）的 `on_chain_end` 事件输出里手动记录，这也是 `done` 事件"以节点输出为准、而非本地 token 拼接"的原因——拼接结果可能因丢包/解析误差与权威结果不一致。

### v2 事件详解：类型、时机与用法

`version="v2"` 时，每个事件是一个 dict，通用结构如下：

```python
{
    "event":  "on_chat_model_stream",   # 事件名，格式 on_[类型]_(start|stream|end)
    "name":   "reply",                  # 产生事件的 Runnable 名（图内即节点/模型名）
    "run_id": "...",                    # 本次执行的随机 ID，子 Runnable 各有独立 ID
    "parent_ids": ["...", "..."],       # 从根到直接父级的 ID 链（仅 v2 提供）
    "tags":      [...],                 # 继承自父级的标签
    "metadata":  {"langgraph_node": "reply", ...},  # 元数据；LangGraph 在此注入节点名
    "data":     {...},                  # 载荷，字段随事件类型而变（见下）
}
```

**`data` 载荷的三个核心字段**（`EventData`，视事件阶段出现）：

| 字段 | 出现阶段 | 含义 |
|------|----------|------|
| `input` | start / end | 该 Runnable 的输入；可流式输入的 Runnable 要到 end 才完整 |
| `chunk` | stream | 一个输出增量片段；同源的 chunk 累加即等于最终 output |
| `output` | end | 该 Runnable 的最终完整输出（start/stream 阶段没有） |

**事件命名规则**：`on_[runnable类型]_(start|stream|end)`。类型有 `chat_model`（聊天模型）、`llm`（非聊天模型）、`prompt`（提示模板）、`tool`（工具）、`retriever`（检索器）、`chain`（绝大多数 Runnable，含 LangGraph 节点与子链）；`start`/`stream`/`end` 分别对应开始、流式中、结束三个时机。

#### 各事件何时触发、如何用

| 事件 | 触发时机 | `data` 关键字段 | 典型用法 |
|------|----------|----------------|----------|
| `on_chat_model_start` | LLM 开始生成 | `input.messages` | 标记"开始思考"、初始化 UI loading 状态 |
| `on_chat_model_stream` | LLM 每产出一个 token | `chunk`（`AIMessageChunk`） | **真流式的核心**：逐 token 转发给前端。本项目用它实现 `token` 事件 |
| `on_chat_model_end` | LLM 生成完毕 | `output`（完整 `AIMessage`） | 拿到完整回复做记录/兜底 |
| `on_chain_start` | 一个节点/子链开始 | `input` | 追踪节点何时进入 |
| `on_chain_stream` | 节点流式输出中间结果 | `chunk` | 节点内部有流式输出时捕获（较少直接用） |
| `on_chain_end` | 一个节点/子链完成 | `output` | **取节点权威结果**：本项目据此发 `intent`/`done` |
| `on_prompt_start` / `on_prompt_end` | 提示模板渲染前/后 | `input` / `output`（`ChatPromptValue`） | 调试最终发给 LLM 的 prompt |
| `on_tool_start` / `on_tool_end` | 工具调用前/后 | `input` / `output` | 追踪工具调用（本项目未用工具） |
| `on_retriever_start` / `on_retriever_end` | 检索器调用前/后 | `input.query` / `output`（文档列表） | 追踪检索结果 |
| `on_custom_event` | 用户主动 `adispatch_custom_event` | 任意（仅 v2 支持） | 自定义业务进度事件 |

> 还有一组 `on_llm_*`（非聊天模型）与上面 `on_chat_model_*` 对应；本项目用聊天模型，故只关心后者。

#### 在本项目中的实践要点

1. **用 `metadata.langgraph_node` 定位节点。** LangGraph 会把当前节点名注入 `metadata`，节点内子链（prompt|llm 等）会继承该值。因此判断"某节点本身完成"必须**同时**满足 `event == "on_chain_end"` 且 `name == metadata.langgraph_node`（`api/chat.py` 中的 `is_node_end`），否则会把子链的 `on_chain_end` 误判为节点结果。
2. **流式 token 只认 `on_chat_model_stream`。** 只有 `reply`（`teaching.agenerate_reply`）与 `progress`（`teaching.arender_progress_report`）节点内部用 `chain.astream` 逐 token 聚合，token 事件才能冒泡出图被捕获；`quiz`/`grade`/`chat` 分支无 LLM 流（grade 的判分回复是组装好的文本），只能靠 `on_chain_end` 一次性取全文。
3. **用过滤参数减少噪声。** `astream_events` 支持 `include_names`/`include_types`/`include_tags` 与对应 `exclude_*`，可只订阅关心的节点/类型，避免遍历全部中间事件。例如只关心 LLM token：`include_types=["chat_model"]`。

## 测验判分闭环

出题、作答、判分、画像更新构成完整闭环，核心是 **quiz_id 落库模式**：

```
出题（/chat/quiz/stream 或聊天内"出道题考考我"）
   │  生成题目 → learner_repo.create_attempt 落库 quiz_attempts(status=pending)
   │  返回 quiz_id（正确答案只存数据库，不经前端流转）
   ▼
作答（测验页提交 或 聊天内"我选B"）
   ▼
判分（/chat/quiz/submit 或工作流 grade 节点）
   │  grading.grade_answer → {is_correct, score, misconception, diagnosis}
   ▼
learner_repo.submit_attempt：回填判分结果 + 同事务更新掌握度
```

**判分策略分层**（`services/grading.py`）：确定性场景不调 LLM，非确定性场景才用 LLM 且有兜底。

| 场景 | 策略 | 说明 |
|------|------|------|
| 选择题（答案为标准字母） | **本地字母比对**，不调 LLM 判对错 | 提取双方字母精确比较，省钱省时、不受 LLM 波动影响；仅答错时调一次 LLM 生成错因诊断 |
| 选择题（答案非字母，LLM 出题未守格式） | 降级 LLM 判分 + 告警日志 | 避免"学生答什么都不对"的静默错误 |
| 填空 / 简答 | LLM 判分（允许等价表述，可给部分分） | 输出【判定】【得分】【错因】【诊断】四段式，解析失败兜底为规范化字符串比对 |

**字母提取的陷阱**（`_extract_choice_letter`）：学生答"A不对，应该选B"，若取全串第一个字母会误判为 A。解法是**显式模式优先**——先匹配"选X / 答案是X / 整句单字母"，都没有才兜底取全串第一个 A-D。

**幂等与并发安全**（`submit_attempt`）：判重用**条件更新**在写事务内完成，而非"先读 status 再写"：

```python
result = await session.execute(
    update(QuizAttempt)
    .where(QuizAttempt.quiz_id == quiz_id, QuizAttempt.status == "pending")
    .values(user_answer=..., is_correct=..., status="submitted", ...)
)
if result.rowcount == 0:
    # 已被并发提交（或不存在）：幂等读取既有结果返回
    ...
# rowcount == 1：仅此一方继续更新掌握度，EMA 不会重复累计
```

双击提交、聊天内外同时作答等并发场景下，只有一方能完成认领，掌握度绝不重复累计，也不会撞 `uq_mastery_subject_kp` 唯一约束。

## 学习者画像

两张表、两种语义（`db/models.py`）：

| 表 | 语义 | 说明 |
|----|------|------|
| `quiz_attempts` | **事实表**（只增不改） | 每一次出题-作答尝试的完整记录；错题本即 `is_correct=False` 的已提交记录，不单独建表 |
| `knowledge_mastery` | **派生物化视图** | 由事实表聚合的掌握度，可从事实表重建；`(subject, knowledge_point)` 唯一 |

**掌握度算法**（`services/learner.py`）：EMA（指数加权平均）+ 时间遗忘衰减。选它而非 IRT/贝叶斯知识追踪，因为单机场景可解释性优先——教师家长能看懂"最近表现权重更高、两周不练会衰减"：

```python
EMA_ALPHA = 0.4              # 新一次作答占四成，历史占六成
DECAY_HALF_LIFE_DAYS = 14    # 遗忘半衰期：14 天不练，旧掌握度衰减一半

def update_mastery(old: float, score: float, days_since_last: float) -> float:
    decayed = old * (0.5 ** (max(days_since_last, 0.0) / DECAY_HALF_LIFE_DAYS))
    return round(decayed * (1 - EMA_ALPHA) + score * EMA_ALPHA, 4)
```

新知识点首次作答不衰减（`days=0`），掌握度从 `score × 0.4` 起步，随作答累积——可解释的冷启动。

**学情查询链路**：学生说"我的学习进度怎么样" → 意图识别（进度查询）→ `progress` 节点聚合 `learner_repo.get_subject_report`（答题数/正确率/薄弱与优势知识点/近 7 天作答）→ LLM 包装成教师口吻的报告（`arender_progress_report`，astream 逐 token 冒泡出图，真流式）→ 异常时降级为模板字符串（`format_progress_fallback`），保证进度查询永远有回应。

## 韧性设计：重试、降级、熔断、限流

LLM 供应商的故障分两类，系统对它们的处理策略根本不同——**错误分类是所有韧性决策的前提**（`app/core/resilience.py` 的 `is_transient_llm_error`）：

| 故障类型 | 例子 | 策略 |
|----------|------|------|
| 瞬时故障 | 429 限流、超时、连接失败、5xx | SDK 有限重试 → 持续发生则熔断 fail-fast → 友好提示"模型繁忙"（503） |
| 永久错误 | 400 参数错误、401 鉴权失败、代码 bug | 不重试、不计入熔断，按普通异常暴露（500 + 完整日志） |

组件实现在 `app/core/resilience.py`（错误分类 + `CircuitBreaker` + `RateLimiter`），接线在 `api/chat.py` 的全部 LLM 端点。

### 重试（Retry）

- **位置**：openai SDK 层。`teaching.py` / `intent.py` 的 `get_llm()` 显式设置 `max_retries=settings.LLM_MAX_RETRIES`（默认 3）——是显式设计，而非依赖 SDK 默认值（2 次）的"碰巧有"。
- **重试对象**：仅 SDK 判定的瞬时错误（429 / 超时 / 连接失败 / 5xx），指数退避。
- **封顶理由**：供应商过载时无限重试会加剧拥塞（retry storm）；且交互路径上每次重试都会拉长 TTFT。
- **与离线路径的区别**：教材入库的 embedding 调用另有 `embed_with_retry`（`ingest_core.py`，3 次退避）。离线批量任务可以激进重试（失败重来成本高），在线交互路径必须克制（用户体感优先）。

### 降级（Degradation）

按"能否无损替代"选择降级形态，分层设计：

| 层 | 场景 | 降级形态 |
|----|------|----------|
| 错误分类 | LLM 瞬时故障 | 用户收到"模型繁忙，请稍后重试"（明确可行动），HTTP **503** 而非笼统 500；SSE 走 `error` 事件 |
| 模板兜底 | 学情报告 | LLM 失败时 `format_progress_fallback` 用结构化数据渲染模板——报告永不为空 |
| 检索降级 | BM25 索引失败 | 自动降级为纯向量检索，主链路不受影响 |
| 诚实兜底 | 检索不充分 | prompt 拼接 `_FALLBACK_NOTE`，引导模型说明"教材未找到依据"而非编造 |
| **不做兜底** | 教学回复（reply） | 无法模板化，强行兜底 = 答非所问。依赖 checkpointer 不落脏数据（见下），用户重发即可安全重来 |

**关键设计：失败重发是天然安全的。** 图执行中断时 checkpointer 不会写入本轮 checkpoint，学生那句提问不会进入会话记忆——不会出现"AI 记得你问过但你没收到回答"的状态错乱。

### 熔断（Circuit Breaker）

针对供应商**持续**过载（如 429 持续十几秒、SDK 重试耗尽）的场景：

```
closed ──连续瞬时故障 ≥ LLM_CIRCUIT_FAILURE_THRESHOLD(默认3)──▶ open（fail-fast）
open ──冷却 LLM_CIRCUIT_RECOVERY_SECONDS(默认60s)──────────────▶ half-open（放行一次试探）
half-open ──试探成功──▶ closed；──试探失败──▶ open（重新冷却）
```

- **开启期间**：`/chat`、`/chat/stream` 在入口处直接返回 503（不调供应商）——用户秒级收到提示而非白等多次重试超时，供应商同时获得恢复窗口。
- **只计瞬时故障**：永久错误（代码 bug、参数错误）不熔断，否则一个坏请求会误伤所有正常用户。
- **记账点**：`chat.py` 全部 LLM 端点（`/chat`、`/chat/stream`、`/quiz`、`/quiz/stream`、`/quiz/submit`）的成功/失败都会汇报；半开状态下任何一条链路试探成功都会恢复闭合。
- **内存实现**：进程级单例，重启自动重置；多实例部署需换共享存储实现。

### 限流（Rate Limiting）

- **对象**：`/chat`、`/chat/stream`，按 `session_id` 滑动窗口（默认 20 次 / 60 秒）。
- **动机**：防前端误触连发、脚本刷量打爆供应商配额——本质也是成本控制。
- **超限行为**：返回 429"提问过于频繁，请稍等片刻"；**不**计入熔断（这是客户端行为，不是供应商故障）。
- **内存实现**：单机部署适用；多实例需换 Redis 等共享存储。

### 配置项（`.env`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `LLM_MAX_RETRIES` | 3 | SDK 层瞬时错误自动重试次数（指数退避） |
| `LLM_CIRCUIT_FAILURE_THRESHOLD` | 3 | 熔断开启所需的连续瞬时故障次数 |
| `LLM_CIRCUIT_RECOVERY_SECONDS` | 60 | 熔断冷却期（秒），过后半开试探 |
| `CHAT_RATE_LIMIT_MAX_CALLS` | 20 | 单会话限流窗口内最大对话请求数 |
| `CHAT_RATE_LIMIT_WINDOW_SECONDS` | 60 | 限流窗口（秒） |

### 与可观测性的配合

熔断开启/恢复打 WARNING/INFO 日志；瞬时故障的完整现场（intent/retrieve 成功、reply 失败）在 Langfuse trace 中可见。429 风暴期间可结合 trace 的延迟分布判断是供应商容量问题还是自身流量异常。

## 向量化增量更新机制

系统采用 **chunk 级增量更新**：教材内容被局部修改后，只有真正变化的 chunk 会重新生成向量，其余 chunk 直接复用。核心逻辑在 `app/services/ingest_core.py`，`scripts/ingest_textbooks.py` 与管理后台入库服务两个入口共用。

**工作流程：**

```
文件 sha256 未变 ──→ 完全跳过
        │ 变了
        ▼
按 Markdown 标题切分（## 章 → ### 课，超长二次切分）
        ▼
每个 chunk 计算内容指纹（正文 + 章/课标题）
        ▼
与向量库中的旧 chunk 逐一 diff
   ├── 指纹未变 → 复用旧向量，零 embedding
   ├── 指纹变了 → 仅这些 chunk 重新 embedding
   └── 旧有新无 → 从库中删除
        ▼
先 embedding 成功 → upsert 新 chunk → 再删除过期 chunk
```

**关键设计：**

| 设计 | 说明                                                                                                                                                                    |
|------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 稳定 chunk ID | 格式 `{文件名}_h{内容哈希[:12]}`（如：`人教版2024七年级上册社会_教材梳理知识库_h0898f841fcd9`），由内容决定而非切分顺序。改一行只改变该 chunk 的 ID，其余 ID 稳定可复用 |
| metadata | 格式`{"version": "人教版","year": "2024","grade": "七年级","semester": "上册","subject": "社会","content_type": "教材梳理知识库"}` |
| 内容指纹 | 覆盖正文 + `chapter`/`lesson` 标题（标题改名会更新 metadata，因此也触发该 chunk 重新入库）                                                                              |
| 先 embedding 后写库 | embedding 是最易失败的外部调用（限流/超时）。只有成功拿到向量后才动库，**失败时旧数据原样保留**，不会丢失                                                               |
| upsert + 先增后删 | 任何时刻库中都有完整数据，不存在"删了新数据没进"的空窗                                                                                                                  |
| 失败重试 | embedding 分批请求（每批 32 条），失败指数退避重试 3 次                                                                                                                 |
| 失败隔离 | 批量脚本中单个文件失败不影响其他文件，脚本最终以非零退出码报告（可接入 CI/定时任务告警）                                                                                |
| 数据自愈 | 管理后台入库前会抽样验证向量库数据（`_verify_chromadb_data`，抽前 3 个 chunk ID）：索引在但库数据丢失时自动执行全量修复。防的是 collection 级"全有或全无"故障，故小样本即可；判定用 `any()`，偏向"认为数据在"，避免误触发昂贵的全量重建 |

**索引文件** `backend/data/ingest_index.json`（v2 格式）按 chunk 粒度记录：

```json
{
  "version": 2,
  "files": {
    "textbook/xxx.md": {
      "sha256": "文件整体哈希",
      "chunk_count": 115,
      "metadata": { "subject": "...", "grade": "..." },
      "chunks": [{ "id": "xxx_ha1b2c3d4e5f", "hash": "..." }]
    }
  }
}
```

**与检索的关系：**

- 检索**不读取 chunk ID**，只依赖 metadata 字段（`subject` / `grade` / `semester` / `content_type` / `chapter` / `lesson`）与正文。chunk ID 规则（v1 序号 / v2 哈希）对检索完全透明。
- 入库/删除成功后自动调用 `keyword_search.invalidate_cache()` 清空 BM25 缓存，下次检索时按最新数据重建（毫秒级）。
- 「先增后删」的双版本窗口（秒级）内，查询可能命中一次旧版本 chunk，随后被清理。

### 入库特别提醒

1. **修改切分逻辑 ≈ 全量重建。** 调整 `text_splitter.py` 的切分规则或 `MAX_CHUNK_CHARS`（当前 480 字符，为适配 bge-large-zh 等模型的 512 token 上限），会使所有 chunk 的内容指纹变化，下次入库将对全部教材重新 embedding。这是预期行为，但要在低峰期操作并预留时间。
2. **更换 Embedding 模型不能用增量机制。** 向量空间整体失效，必须清空向量库全量重建，详见根目录 README 的「Embedding 模型配置警告」。
3. **`ingest_index.json` 与 `chroma_db/` 必须同进同退。** 两者是一致性的一组状态：备份要一起备份，删除要一起删除。若单独删除了 `chroma_db/` 想重建，请同时删除 `ingest_index.json`（否则脚本会认为文件"未变更"而跳过；管理后台入口虽能检测缺失并自动修复，但保持两者一致是最稳妥的做法）。
4. **改教材文件名 = 新文件全量入库 + 旧文件自动清理。** chunk ID 以文件名（不含扩展名）为前缀，改名后旧 chunk 全部失效。同名文件内容修改则走增量。
5. **短暂的"双版本"窗口是刻意的取舍。** 变更的 chunk 采用先增后删，新旧两版会共存几秒，期间查询可能命中一次旧版本。这是用"短暂双版本"换取"零数据丢失窗口"，对教材场景完全可接受。
6. **文件内完全重复的段落**会得到 `_1`/`_2` 序号后缀的 chunk ID。若在此类重复段落之前有增删导致后缀错位，这几个重复块会被视为变更而重新 embedding——影响仅限重复块，属正常现象。
7. **v1 → v2 平滑迁移。** 旧版按序号 ID（`{文件名}_chunk_{i}`）的索引仍然兼容：文件未变更时照常跳过，下次内容变更时自动清理旧序号 ID 并迁移到 v2 格式，无需手工干预。

## Langfuse 应用接入（可观测性设计）

LLM 全链路可观测性由 [Langfuse](https://langfuse.com/) 承担（**SDK v4**，基于 OpenTelemetry，经 OTLP 异步批量上报）。**接入是可选的**：`.env` 不配置密钥时所有埋点自动降级为 no-op，业务行为与性能零影响。服务端自托管部署见下节「Langfuse 部署」。

### 三类探针：按代码形态选择，而非改造代码

Langfuse v4 的追踪基座是 OpenTelemetry，不是 LangChain——LangChain callback 只是其中一种自动探针。三种探针互补，产出的 span 基于 OTel 上下文自动嵌套进同一条 trace：

| 探针 | 适用场景 | 本项目使用点 |
|------|----------|--------------|
| LangChain `CallbackHandler` | LangChain/LangGraph 流量，自动记录 prompt、completion、token 用量、耗时 | `/chat`、`/chat/stream` 的图入口 config；quiz 直连链；教材生成后台任务 |
| `@observe` 装饰器 | 非 LangChain 代码（检索、后台任务）手动埋 span | `rag.py` 的 `retrieve` / `aretrieve` / `aretrieve_checked`（`as_type="retriever"`）；`textbook_generator` 的 `generate_outline` / `generate_textbook` |
| `trace_span` + `create_score` | 需要回写评分的业务节点 | `/chat/quiz/submit`：判分结果回写为 `quiz_correct` 布尔 Score，便于在后台筛选答错 trace 做错因分析 |

### 统一入口：`app/core/observability.py`

业务模块不直接 import langfuse，全部通过这一层访问，未启用时优雅降级：

| 函数 | 作用 | 未启用时行为 |
|------|------|--------------|
| `langfuse_enabled()` | 判定开关（密钥齐备且 `LANGFUSE_ENABLED`） | — |
| `get_langfuse_handler()` | CallbackHandler 单例（`@lru_cache`） | 返回 `None` |
| `callback_config(tags, session_id, trace_name)` | 构造 RunnableConfig 片段（callbacks + metadata：`langfuse_tags` / `langfuse_session_id` / `langfuse_trace_name`） | 返回 `{}`，可直接作 config 传入 |
| `observe` | `@observe` 安全包装，支持 `@observe` / `@observe(...)` 两种用法 | 透传原函数 |
| `trace_span(name, as_type)` | span 上下文管理器 | yield `None` |
| `create_score(name, value, ...)` | 向当前活动 trace 回写评分（v4 API：`score_current_trace`） | 静默跳过 |
| `flush_langfuse()` | 排空 OTLP 上报队列 | 静默跳过 |

### 接入点明细

| 位置 | 埋点方式 | 说明 |
|------|----------|------|
| `api/chat.py` `/chat`、`/chat/stream` | config 注入 callback + `langfuse_session_id` + `langfuse_trace_name`（`"chat"` / `"chat-stream"`） | **图统一入口**：handler 挂在这里，图内所有节点（intent/retrieve/reply/quiz/grade/progress）的 LLM 调用经 RunnableConfig contextvar 自动继承，agent.py 零改动；`session_id` 使多轮对话按会话聚合；`trace_name` 让 Tracing 视图显示业务名而非默认的 "LangGraph" |
| `api/chat.py` `/chat/quiz`、`/chat/quiz/stream` | `trace_span("quiz-generate" / "quiz-generate-stream")` 包裹检索 + 出题 | **一条完整链路**：@observe 的检索 span 与出题链 generation 嵌套进同一 trace；`/quiz` 的 `asyncio.to_thread` 会复制 contextvars，OTel 上下文随线程传播，跨线程嵌套不断裂；span 的 input 记出题参数，output 记 quiz_id 与题干 |
| `api/chat.py` `/chat/quiz/submit` | `trace_span("quiz-grade")` + `create_score` | 判分链在 span 内执行（嵌套进同一 trace），判分结果回写 Score；span 的 input 记 `quiz_id`/`question_type`，output 记判分结果 |
| `services/rag.py` 三个检索入口 | `@observe(as_type="retriever")` | 检索不走 LangChain Runnable，callback 抓不到；装饰器把整个混合检索（向量+BM25+RRF）记为一个 retriever span，query、命中、耗时全可见 |
| `services/textbook_generator.py` | `@observe` + 逐章 invoke 传 config + 末尾 `flush_langfuse()` | 教材生成跑在 BackgroundTasks 线程池，**OTel 上下文不跨线程**，需在任务函数内显式挂 callback 并在结束时 flush |
| `services/grading.py` | `grade_answer` 加 `config` 参数透传至 `_llm_grade` / `_llm_diagnosis` | 图内调用靠 contextvar 自动继承；直连路径（submit 端点）由调用方传入 |
| `main.py` lifespan | 关闭时 `flush_langfuse()` | v4 事件走 OTLP 异步批量上报，进程退出前必须排空，否则丢尾部数据 |

### Tracing 视图的 Name 来源

Langfuse 的 Tracing 列表中 Name 列取**每条 trace 根观测的名字**，规则按优先级：

1. metadata 里的 `langfuse_trace_name`（CallbackHandler 在链根读取，`CallbackHandler.py:506`）——本项目的 `chat` / `chat-stream` / `quiz-grade` 等即由此命名
2. `@observe(name=...)` / `trace_span(name=...)`——手动埋点无外层 trace 时自己成根，如教材生成的 `generate-textbook`
3. 默认取 LangChain Runnable 名（如 `LangGraph`、`RunnableSequence`）——不显式命名时 Tracing 视图会被这些无业务语义的名字刷屏

如需按用户维度聚合（Users 视图），在 metadata 里加 `langfuse_user_id` 即可（当前系统无账号体系，未启用）。

### 配置项（`.env`）

| 变量 | 说明 |
|------|------|
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | 项目 API 密钥对（`pk-lf-` / `sk-lf-` 前缀，不可互换）。**留空即整体关闭监控** |
| `LANGFUSE_HOST` | 服务地址，云端或自托管。**不要带末尾斜杠**（见故障排查）；`observability.py` 已做 `rstrip("/")` 兜底 |
| `LANGFUSE_ENABLED` | 总开关，默认 `True`，置 `False` 可在密钥保留的情况下临时关闭 |

### 接入侧故障排查

**验证连通性**（不改业务、不泄露密钥）：

```bash
cd backend && .venv/Scripts/python -c "
import os
from app.core.config import get_settings
s = get_settings()
os.environ['LANGFUSE_PUBLIC_KEY'] = s.LANGFUSE_PUBLIC_KEY
os.environ['LANGFUSE_SECRET_KEY'] = s.LANGFUSE_SECRET_KEY
os.environ['LANGFUSE_HOST'] = s.LANGFUSE_HOST.rstrip('/')
from langfuse import get_client
print('auth_check:', get_client().auth_check())
"
```

| 症状 | 原因 | 处理 |
|------|------|------|
| `Failed to export span batch code: 401` | 密钥无效：填反了（pk/sk 前缀互换）、复制了 UI 掩码值（真实密钥约 42 字符，只在创建时完整显示一次） | 到 Langfuse Settings → API Keys 新建密钥对并完整复制 |
| 先 308 跳转再 500 | `LANGFUSE_HOST` 带末尾斜杠，SDK 拼出 `//api/...` 双斜杠路径触发 308，代理转发跳转请求时损坏 | 去掉末尾斜杠（代码已兜底 `rstrip`） |
| 持续 500，且仅真实对话流量报错（手动小 span 正常） | **服务端 S3/MinIO 故障**——generation 观测的 IO 要先上传 S3，普通 span 不走该路径，故只有真实 LLM 流量失败 | 服务端 `docker compose logs langfuse-web \| grep -i s3` 定位，见下节部署文档 |
| 上报失败但业务正常 | 预期行为：上报是异步批量的，任何导出异常都不影响请求响应 | 修复服务端后自然恢复 |

**SDK 版本注意**：本项目锁定 `langfuse>=4.0`。v3 的 `get_trace_context()` / `create_score(trace_id=...)` 在 v4 已移除，对应 `get_current_trace_id()` / `score_current_trace()`；网上大量教程仍是 v2 写法（`langfuse.callback.CallbackHandler`），不可照搬。

## Langfuse 部署（Docker Compose 自托管）

本项目使用 Langfuse 做 LLM 可观测性（trace 链路追踪）。以下为自托管部署的完整记录与踩坑总结。

### 部署架构

`docker compose up` 一键启动 6 个容器，无需单独安装任何依赖服务：

| 服务 | 作用 | 端口 |
|---|---|---|
| langfuse-web | Web UI 和 API | 3000（对外） |
| langfuse-worker | 后台异步处理 | 3030（仅本机） |
| postgres | 配置、项目、用户等元数据 | 5432（仅本机） |
| clickhouse | traces/observations 遥测数据 | 8123/9000（仅本机） |
| redis | 队列和缓存 | 6379（仅本机） |
| minio | 对象存储（事件、媒体文件） | 9090（对外）、9091（仅本机） |

**只需要两个文件**，放在同一目录（如 `/home/projects/langfuse`）：

```bash
mkdir -p /home/projects/langfuse && cd /home/projects/langfuse
wget https://raw.githubusercontent.com/langfuse/langfuse/main/docker-compose.yml
```

### .env 配置

compose 文件里所有 `${XXX:-默认值}` 变量从同目录的 `.env` 读取。**不需要复制仓库里的 `.env.dev.example` / `.env.prod.example`**——那些是给源码开发/构建用的，与镜像部署无关，直接复制反而会引入冲突变量。

`.env` 是可选的（不配则用公开默认值启动），但生产环境必须自建，最小模板：

```bash
# 访问地址：浏览器地址栏输入什么就填什么，云服务器填公网 IP 或域名
# 注意：不能填 0.0.0.0（那是监听地址语义，NextAuth 用它生成回调/重定向 URL）
NEXTAUTH_URL=http://<服务器IP或域名>:3000

# 三个密钥分别用 openssl rand -hex 32 生成
NEXTAUTH_SECRET=<随机密钥1>
SALT=<随机密钥2>
ENCRYPTION_KEY=<随机密钥3>

# PostgreSQL 密码（两处必须一致）
POSTGRES_PASSWORD=<PG密码>
DATABASE_URL=postgresql://postgres:<PG密码>@postgres:5432/postgres

# ClickHouse / Redis 密码
CLICKHOUSE_PASSWORD=<ClickHouse密码>
REDIS_AUTH=<Redis密码>

# MinIO 密码（四处必须一致）
MINIO_ROOT_PASSWORD=<MinIO密码>
LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY=<MinIO密码>
LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY=<MinIO密码>
LANGFUSE_S3_BATCH_EXPORT_SECRET_ACCESS_KEY=<MinIO密码>

# 可选：关闭遥测上报
TELEMETRY_ENABLED=false
```

**填写规则（易踩坑）：**

1. 密码只用字母和数字。`#`、`@`、`/`、`$` 等特殊字符在连接串和 shell 解析中会出问题。推荐 `openssl rand -hex 16` 生成。
2. 一致性是核心：`DATABASE_URL` 里的密码 = `POSTGRES_PASSWORD`；三个 `LANGFUSE_S3_*_SECRET_ACCESS_KEY` = `MINIO_ROOT_PASSWORD`。
3. 格式为 `KEY=value`：不加引号、等号两边无空格、注释单独成行（不要行尾注释）。
4. 这些密码只用于 Docker 内部网络的容器间通信（postgres/redis/clickhouse 端口均绑定 127.0.0.1），不是给用户用的，第一次启动时由 postgres 容器按 `POSTGRES_PASSWORD` 初始化。

### 无头初始化（LANGFUSE_INIT_*）

可在 `.env` 预置组织/项目/管理员账号/API Key，免去网页注册：

```bash
LANGFUSE_INIT_ORG_ID=my-org          # 总开关！不设则其余 INIT 变量全部被忽略
LANGFUSE_INIT_ORG_NAME=my-org
LANGFUSE_INIT_PROJECT_ID=my-project
LANGFUSE_INIT_PROJECT_NAME=my-project
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=pk-lf-<自定义>   # pk-lf- 前缀 + 任意字符串
LANGFUSE_INIT_PROJECT_SECRET_KEY=sk-lf-<自定义>   # sk-lf- 前缀，不能与公钥相同
LANGFUSE_INIT_USER_EMAIL=admin@example.com
LANGFUSE_INIT_USER_NAME=admin
LANGFUSE_INIT_USER_PASSWORD=<至少8位>
```

**关键行为（依据 `web/src/initialize.ts` 源码）：**

- **`LANGFUSE_INIT_ORG_ID` 是总开关**：不设它，其他所有 `LANGFUSE_INIT_*` 静默忽略（日志只有一条 warning）。这是"配了账号却登录不上"的最常见原因。
- 初始化是幂等的（upsert），重复启动不会重复创建。
- **用户已存在则不会重置密码**（`if (!userId)` 才创建）。改过密码想生效，需换新邮箱，或删库中旧用户后重建：
  ```bash
  docker compose exec postgres psql -U postgres -d postgres -c "DELETE FROM users WHERE email='admin@example.com';"
  docker compose up -d --force-recreate langfuse-web
  ```
- PUBLIC_KEY/SECRET_KEY 是**应用接入凭证**（代码里 `Langfuse(public_key=..., secret_key=...)`），不是网页登录凭证；自己定义，启动时写入数据库。也可事后在网页 Settings → API Keys 手动创建，效果相同。

### 日常运维命令

```bash
docker compose pull        # 拉取镜像
docker compose up -d       # 启动/应用配置变更（自动重建受影响容器，无需先 down）
docker compose ps          # 查看状态
docker compose logs -f langfuse-web   # 跟踪日志
docker compose config      # 校验 .env 注入结果与 compose 合法性
```

**重要区分：**

- 改配置后用 `docker compose up -d`（对比配置差异，只重建受影响的容器，数据在 volume 中不受影响）。**不要用 `docker compose restart`**——它不重新加载 `.env`，是"改了不生效"的常见原因。
- `docker compose down` 停掉整套服务（保留数据）；`docker compose down -v` **连数据卷一起删**（彻底重来）。
- 例外：postgres/redis 自身的密码在首次初始化时已固化进数据卷，事后改 `POSTGRES_PASSWORD` 等不会重新应用，会导致连接失败。密码类配置首次部署时定好。

### 登录与接入

浏览器访问 `http://<服务器IP>:3000`：

- 配了 `LANGFUSE_INIT_*`：直接用预设邮箱密码登录；
- 没配：Sign up 注册第一个账号，按引导创建组织和项目，自动生成 API Key 对（Secret Key 只完整显示一次）。

应用侧接入：

```python
from langfuse import Langfuse

langfuse = Langfuse(
    public_key="pk-lf-...",
    secret_key="sk-lf-...",
    host="http://<服务器IP>:3000",   # 指向自部署实例
)
```

### 故障排查

**登录问题按症状定位：**

| 症状 | 方向 |
|---|---|
| 页面打不开 | 查 `docker compose ps`、`docker compose logs langfuse-web`（首次启动要跑迁移，等 1~2 分钟）、防火墙/安全组端口 |
| 提示用户名或密码错误 | 用户没创建成功或密码不对，走下面的三步排查 |
| 提交后跳回登录页无报错 | `NEXTAUTH_URL` 与浏览器实际访问地址不一致（含端口），改后重建 |

**初始化账号未生效的三步排查：**

```bash
# 1. 确认变量注入容器（空值 = .env 该行写法有误）
docker compose exec langfuse-web env | grep LANGFUSE_INIT

# 2. 看初始化日志（"will be ignored" = ORG_ID 缺失；"Partial user configuration" = EMAIL/PASSWORD 只配了一个）
docker compose logs langfuse-web 2>&1 | grep -i "langfuse init"

# 3. 直接查库确认用户是否存在
docker compose exec postgres psql -U postgres -d postgres -c "SELECT email, name FROM users;"
```

**国内拉取镜像失败（Docker Hub 被墙/DNS 污染）：**

典型报错：`failed to resolve reference ... dial tcp 157.240.x.x:443: i/o timeout`（DNS 污染到错误 IP）。解法：

1. 配置镜像加速器（`/etc/docker/daemon.json`）：
   ```json
   {
     "registry-mirrors": [
       "https://docker.1ms.run",
       "https://docker.m.daocloud.io",
       "https://dockerproxy.net"
     ]
   }
   ```
   然后 `systemctl daemon-reload && systemctl restart docker`。
2. **`registry-mirrors` 只对 `docker.io` 生效**。compose 里 `docker.langfuse.com/langfuse/xxx` 是官方别名，不走加速器，需改为 `langfuse/langfuse:4`、`langfuse/langfuse-worker:4`（同一镜像）。
3. `cgr.dev/chainguard/minio` 拉不动时可换成 `minio/minio:latest`（entrypoint/健康检查均兼容）。
4. 兜底：从镜像站手动拉取打 tag，如 `docker pull docker.m.daocloud.io/langfuse/langfuse:4 && docker tag docker.m.daocloud.io/langfuse/langfuse:4 langfuse/langfuse:4`。

**参考：** [官方 docker-compose.yml](https://github.com/langfuse/langfuse/blob/main/docker-compose.yml) ｜ [自托管文档](https://langfuse.com/self-hosting/docker-compose) ｜ [初始化源码](https://github.com/langfuse/langfuse/blob/main/web/src/initialize.ts)
