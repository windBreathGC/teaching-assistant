# 中学伴学助教 - 后端

FastAPI 后端服务，提供教材检索（RAG）、AI 对话、随堂测验等 API。

> 项目整体介绍、安装与启动方式见根目录 [README.md](../README.md)。本文档收录后端的**设计与实现细节**：流式接口（SSE）契约、知识检索（混合检索 + RRF 融合）、LangGraph 对话工作流、向量化增量更新机制。

## 流式响应设计（SSE）

### 概述

对话与出题各有一对接口：非流式返回完整 JSON，流式通过 SSE 逐 token 推送。

| 接口 | 方式 | 说明 |
|------|------|------|
| `POST /chat` | 普通 JSON | 一次性返回完整回复 |
| `POST /chat/stream` | SSE | 意图识别 → 逐 token 生成 → 收尾汇总 |
| `POST /chat/quiz` | 普通 JSON | 一次性返回完整题目 |
| `POST /chat/quiz/stream` | SSE | 逐 token 生成题目 → 解析后收尾 |

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

data: {"type": "token", "content": "这"}
data: {"type": "token", "content": "道"}
data: {"type": "token", "content": "题"}
...（逐 token 推送，数量不定）

data: {"type": "done", "reply": "完整回复全文", "suggested_actions": ["出道例题", "总结重点"]}
```

| 事件 | 时机 | 字段 | 说明 |
|------|------|------|------|
| `intent` | 流开始，仅一次 | `intent` | 意图识别结果（知识问答 / 课程讲解 / 测验请求 / 自由聊天） |
| `token` | 生成中，零到多次 | `content` | 一个增量文本片段，前端按序拼接即为完整回复 |
| `done` | 正常结束，仅一次 | `reply`、`suggested_actions` | `reply` 为完整回复全文（与全部 token 拼接结果一致）；`suggested_actions` 为建议的后续操作（最多 3 条） |
| `error` | 任何阶段异常时 | `detail` | 用户可读的错误提示；发送后连接结束 |

#### `POST /chat/quiz/stream` 事件序列

```
data: {"type": "token", "content": "【"}
...（逐 token 推送题目原文）

data: {"type": "done", "question": "...", "options": ["A. ...", "B. ..."], "correct_answer": "A", "explanation": "...", "knowledge_point": "..."}
```

| 事件 | 时机 | 字段 | 说明 |
|------|------|------|------|
| `token` | 生成中，零到多次 | `content` | 题目原文的增量片段 |
| `done` | 正常结束，仅一次 | `question`、`options`、`correct_answer`、`explanation`、`knowledge_point` | 后端将全部 token 拼接后经 `parse_quiz_output` 解析出的结构化题目；`options` 仅选择题有值，其余题型为 `null` |
| `error` | 任何阶段异常时 | `detail` | 同上 |

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
  → 按 payload.type 分发：token → onToken / done → onDone / error → onError
```

### 修改协议时的注意事项

1. **前后端必须同步修改**：事件类型名、字段名的任何改动都要同时改 `backend/app/api/chat.py` 和 `frontend/src/api/client.ts`，否则前端解析失败。
2. **未知事件类型会被前端忽略**：当前 `intent` 事件即属此类——后端发送，前端暂未使用（仅处理 `token`/`done`/`error`）。新增事件类型时，未升级的旧前端会静默跳过，这可以作为平滑升级的利用点。
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

### 调用入口

| 入口 | 位置 | 说明 |
|------|------|------|
| `POST /chat/stream` | `api/chat.py` | 意图识别 → 检索 → 流式生成 |
| `POST /chat` | `services/agent.py` | LangGraph：intent → retrieve → reply（见下节） |
| `POST /quiz[/stream]` | `api/chat.py` | top_k=2 检索后出题 |
| `GET /subjects/{id}/lessons/{id}/content` | `api/subjects.py` | 课文原文（metadata 精确匹配） |

### 检索侧特别提醒

1. **一键全量更新 / ingest 后请重启后端服务。** 课文 ID → 课文名的映射表（`_LESSON_NAME_MAP`）在后端启动时从 `generated/*.json` 构建一次；不重启则新增/改名的课文走不到精确匹配，会静默降级为混合检索，表现为"选了课文但回答不聚焦"。（BM25 索引缓存会自动失效重建，不受此限制。）
2. **向量检索无距离阈值。** 问题与教材无关时，仍会把最相似的 top_k 个 chunk 注入上下文，LLM 可能据此强行作答。对回答质量敏感时可评估增加 distance cutoff。

## LangGraph 工作流

`POST /chat` 走 LangGraph 编排的智能体工作流（`app/services/agent.py`）：意图识别后按条件路由到不同分支，状态（`AgentState`）在节点间流转，携带消息历史、学科/课文上下文与检索结果。

```
                ┌──────────┐
                │  intent  │  意图识别 classify_intent
                └────┬─────┘
                     │ route_by_intent（条件路由）
        ┌────────────┼────────────────┐
        ▼            ▼                ▼
  ┌───────────┐ ┌─────────┐     ┌─────────┐
  │ retrieve  │ │  quiz   │     │  chat   │
  │ RAG 检索   │ │ 生成测验 │     │ 自由聊天 │
  │ top_k=2   │ └────┬────┘     └────┬────┘
  └─────┬─────┘      │               │
        ▼            │               │
  ┌───────────┐      │               │
  │   reply   │      │               │
  │ 生成教学回复│      │               │
  └─────┬─────┘      │               │
        ▼            ▼               ▼
                ┌──────────┐
                │   END    │
                └──────────┘
```

| 节点 | 说明 |
|------|------|
| `intent` | 对最后一条用户消息做意图分类：知识问答 / 课程讲解 / 测验请求 / 自由聊天 |
| `retrieve` | 意图为知识问答/课程讲解时进入：课文名拼入 query，走混合检索（`top_k=2`） |
| `reply` | 检索结果注入 Prompt，LLM 生成教学回复与建议动作 |
| `quiz` | 意图为测验请求：基于检索结果生成选择题（非流式） |
| `chat` | 其他意图：返回引导性欢迎语，不调用 LLM |

> 流式接口 `POST /chat/stream` 不走该图：token 级真流式需要图外的生成调用（图的 `reply_node` 为非流式 `agenerate_reply`），且流式路径已退化为"意图识别 →（可选）检索 → 流式生成"的直线，无分支编排需求，直接平铺调用即可。

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
