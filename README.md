# 中学伴学助教

基于 RAG（检索增强生成）的中学多课程 AI 学习智能体，覆盖语文、数学、英语、科学、社会五门学科，为学生提供教材知识问答、课文讲解、随堂测验、教材管理等个性化学习辅导。

## 功能特性

- **多学科覆盖**：语文（部编版）、数学（浙教版）、英语（人教PEP版）、科学（浙教版）、社会（人教版）
- **多年级支持**：七年级上册、七年级下册（可扩展六至九年级）
- **AI 知识问答**：基于教材内容的 RAG 检索，回答与课本相关的问题
- **混合检索**：向量语义 + BM25 关键词双路召回，RRF 融合排序，兼顾语义理解与术语/课文名精确匹配
- **课文讲解**：自动加载课文原文，AI 逐段讲解重点难点
- **随堂测验**：AI 根据当前章节生成选择题、填空题、简答题
- **章节导航**：按年级 -> 学科 -> 单元 -> 课文的层级结构浏览教材
- **流式响应**：AI 回答采用流式输出，响应更快更自然
- **教材管理后台**：扫描、解析、向量化教材，支持一键全量更新
- **智能采集**：自动解析 Markdown 教材，生成结构化 JSON 元数据与向量化索引
- **教材生成**：根据学科大纲自动生成教材内容
- **任务中心**：异步任务管理，实时查看教材解析、向量化等任务进度
- **模型接入管理**：支持多模型配置、默认模型切换，兼容任意 OpenAI 格式 API

## 技术架构

```
+-------------+      HTTP/REST       +-------------+
|   Vue 3     | <------------------> |   FastAPI   |
|  (前端)      |                      |   (后端)     |
+-------------+                      +------+------+
                                            |
                                   +--------v--------+
                                   |    ChromaDB     |
                                   |  (向量数据库)    |
                                   +-----------------+
                                            |
                                   +--------v--------+
                                   |   SQLite (aiosqlite)
                                   |  (模型配置、任务记录)
                                   +-----------------+
```

### 前端技术栈

- [Vue 3](https://vuejs.org/) + [Vite](https://vitejs.dev/) + [TypeScript](https://www.typescriptlang.org/)
- [Element Plus](https://element-plus.org/) UI 组件库
- [Pinia](https://pinia.vuejs.org/) 状态管理
- [Vue Router](https://router.vuejs.org/) 路由
- [Axios](https://axios-http.com/) HTTP 客户端
- [Markdown-it](https://github.com/markdown-it/markdown-it) + [KaTeX](https://katex.org/) 内容渲染

### 后端技术栈

- [FastAPI](https://fastapi.tiangolo.com/) Web 框架
- [ChromaDB](https://www.trychroma.com/) 向量数据库（教材知识库）
- [bm25s](https://github.com/xhluca/bm25s) BM25 关键词检索（混合召回，字符 n-gram 分词）
- [LangChain](https://www.langchain.com/) + [LangGraph](https://langchain-ai.github.io/langgraph/) AI Agent 编排
- [SQLAlchemy](https://www.sqlalchemy.org/) + [aiosqlite](https://github.com/omnilib/aiosqlite) 异步 ORM / SQLite
- [OpenAI](https://platform.openai.com/) 兼容 API（支持第三方 LLM 平台）
- [uv](https://docs.astral.sh/uv/) Python 包管理（`pyproject.toml` + `uv.lock` 锁定依赖）

## 项目结构

```
.
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── api/               # API 路由（health / subjects / chat / admin）
│   │   ├── core/              # 配置、常量
│   │   ├── db/                # 数据库模型与连接（SQLite）
│   │   ├── models/            # Pydantic 数据模型
│   │   ├── services/          # 业务逻辑（RAG、教学 Agent、教材解析/生成/分析、模型配置、任务管理）
│   │   └── utils/             # 工具函数
│   ├── chroma_db/             # 向量数据库持久化目录
│   ├── data/                  # 结构化数据与 SQLite 数据库
│   │   ├── generated/         # 解析生成的教材 JSON 数据
│   │   ├── subjects/          # 学科元数据清单
│   │   ├── ingest_index.json  # chunk 级增量向量化索引
│   │   └── app.db             # SQLite 数据库
│   ├── scripts/               # 数据导入脚本
│   ├── pyproject.toml         # 项目元信息与依赖声明（uv）
│   ├── uv.lock                # 依赖锁文件（uv）
│   ├── .python-version        # Python 版本固定（uv）
│   └── requirements.txt       # Python 依赖（pip 兼容保留）
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── api/               # HTTP 客户端封装
│   │   ├── components/        # 公共组件（ChatWindow、ModelManager、TaskCenter、SubjectTree 等）
│   │   ├── stores/            # Pinia 状态管理（app、modelStore）
│   │   ├── styles/            # 全局样式与 CSS 变量
│   │   ├── utils/             # 工具函数
│   │   └── views/             # 页面视图（Home、Chat、Quiz、Admin）
│   └── package.json           # Node.js 依赖
├── textbook/                   # 教材原文 Markdown
├── start.py                    # 一键启动脚本
├── start_prod.py               # 生产环境启动脚本
├── .env                        # 环境变量配置
└── .env.example                # 环境变量示例
```

## 快速开始

### 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（推荐的 Python 包管理器）
- Node.js 18+
- （可选）Conda / Miniconda

### 1. 克隆仓库

```bash
git clone <repository-url>
cd teaching-assistant
```

### 2. 配置环境变量

复制示例文件并修改：

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 LLM API 密钥：

| 变量 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `OPENAI_API_KEY` | 是 | LLM API 密钥 | `sk-...` |
| `OPENAI_BASE_URL` | 是 | API 基础地址 | `https://api.openai.com/v1/` |
| `LLM_MODEL` | 否 | 对话模型名称 | `gpt-4o-mini` |
| `EMBEDDING_MODEL` | 否 | 嵌入模型名称（**切换后必须重新向量化全部教材**） | `text-embedding-3-small` |
| `BACKEND_PORT` | 否 | 后端端口（默认 8000） | `8000` |
| `FRONTEND_PORT` | 否 | 前端端口（默认 5173） | `5173` |
| `DEBUG` | 否 | 调试模式（默认 False） | `False` |

> 支持任何 OpenAI 兼容格式的 LLM 平台，如 [SiliconFlow](https://siliconflow.cn/)、[DashScope](https://dashscope.aliyun.com/) 等。

### 3. 安装依赖

**后端（Python，推荐 uv）**

```bash
cd backend
uv sync          # 按 uv.lock 创建 .venv 并安装全部依赖
```

<details>
<summary>使用 pip / Conda 的传统方式</summary>

```bash
# 如果使用 Conda
conda activate learn
# 或使用系统 Python
pip install -r backend/requirements.txt
```

</details>

**前端（Node.js）**

```bash
cd frontend
npm install
```

### 4. 启动服务

**一键启动（推荐）**

```bash
python start.py
```

该脚本会同时启动后端（`http://localhost:8000`）和前端（`http://localhost:5173`）。

> 启动脚本按以下优先级选择 Python 解释器：`PYTHON_PATH` 环境变量 → `backend/.venv`（uv 创建）→ Conda `learn` 环境 → 当前解释器。执行过 `uv sync` 后会自动使用 uv 管理的依赖环境，无需额外配置。

**手动启动**

```bash
# 终端 1 - 后端
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 终端 2 - 前端
cd frontend
npm run dev
```

### 5. 访问应用

打开浏览器访问：http://localhost:5173

## 可用命令

### 前端

| 命令 | 说明 |
|------|------|
| `npm run dev` | 启动开发服务器（热更新） |
| `npm run build` | 生产构建（TypeScript 编译 + Vite 打包） |
| `npm run preview` | 预览生产构建 |

### 后端

| 命令 | 说明 |
|------|------|
| `uv sync` | 安装/同步依赖（在 `backend/` 下执行） |
| `uv add <包名>` | 新增依赖并更新 `pyproject.toml` 与 `uv.lock` |
| `uv export -o requirements.txt` | 从锁文件导出 pip 兼容的依赖清单 |
| `uv run uvicorn app.main:app --reload` | 开发模式启动（热重载） |
| `python -m uvicorn app.main:app --host 0.0.0.0` | 生产模式启动 |
| `python scripts/ingest_textbooks.py` | 手动增量导入教材到向量库 |

## 教材数据

教材原文存放于 `textbook/` 目录，按 Markdown 格式组织：

### 七年级上册

| 文件 | 学科 | 版本 | 年级 |
|------|------|------|------|
| `部编版2024七年级上册语文_完整教材内容.md` | 语文 | 部编版 | 七年级上册 |
| `浙教版2024七年级上册数学_完整教材内容.md` | 数学 | 浙教版 | 七年级上册 |
| `人教PEP版2024七年级上册英语_完整教材内容.md` | 英语 | 人教PEP版 | 七年级上册 |
| `浙教版2024七年级上册科学_完整教材内容.md` | 科学 | 浙教版 | 七年级上册 |
| `人教版2024七年级上册社会_教材梳理知识库.md` | 社会 | 人教版 | 七年级上册 |

### 七年级下册

| 文件 | 学科 | 版本 | 年级 |
|------|------|------|------|
| `部编版2024七年级下册语文_完整教材内容.md` | 语文 | 部编版 | 七年级下册 |
| `浙教版2024七年级下册数学_完整教材内容.md` | 数学 | 浙教版 | 七年级下册 |
| `人教PEP版2024七年级下册英语_完整教材内容.md` | 英语 | 人教PEP版 | 七年级下册 |
| `浙教版2024七年级下册科学_完整教材内容.md` | 科学 | 浙教版 | 七年级下册 |
| `人教版2024七年级下册社会_完整教材内容.md` | 社会 | 人教版 | 七年级下册 |

### 导入教材到向量库

首次部署或教材更新后，可通过管理后台「一键全量更新」功能自动导入，或手动执行导入脚本：

```bash
cd backend
python scripts/ingest_textbooks.py
```

该脚本会将 `textbook/` 下的 Markdown 文件切分并向量化，存入 `backend/chroma_db/`。脚本与支持单文件入库的管理后台服务共用同一套核心逻辑（`backend/app/services/ingest_core.py`），两个入口行为一致。

### 后端设计细节

混合检索（向量 + BM25 双路召回、RRF 融合）、chunk 级增量入库、LangGraph 对话工作流等后端设计与实现细节，统一收录在 [backend/README.md](backend/README.md)：

- 知识检索：三级策略（metadata 精确匹配优先 → 混合检索 → RRF 融合）
- LangGraph 工作流：意图识别 → 条件路由 → 检索/出题/闲聊分支
- 向量化增量更新：chunk 级 diff、稳定 ID、先增后删、数据自愈

## API 接口

后端提供以下 RESTful API：

### 公共接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /` | - | 服务根路径，返回 SPA 或基本信息 |
| `GET /health` | GET | 健康检查 |
| `GET /subjects` | GET | 获取所有学科列表 |
| `GET /subjects/{subject_id}/chapters` | GET | 获取某学科的章节列表 |
| `GET /subjects/{subject_id}/chapters/{chapter_id}/lessons` | GET | 获取某章节下的课文/课时列表 |
| `GET /subjects/{subject_id}/lessons/{lesson_id}/content` | GET | 获取某课文的原文内容 |
| `POST /chat` | POST | AI 对话（非流式） |
| `POST /chat/stream` | POST | AI 对话（SSE 流式，逐 token 返回） |
| `POST /chat/quiz` | POST | 生成测验题目（非流式） |
| `POST /chat/quiz/stream` | POST | 生成测验题目（SSE 流式） |

> 流式接口的 SSE 传输格式与事件协议（`intent` / `token` / `done` / `error`）详见 [backend/README.md](backend/README.md)。

### 管理后台接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /admin/textbooks` | GET | 获取教材扫描列表（解析/向量化状态） |
| `POST /admin/textbooks/parse` | POST | 解析指定教材为结构化 JSON |
| `POST /admin/textbooks/ingest` | POST | 将指定教材向量化入库 |
| `POST /admin/textbooks/ingest-all` | POST | 一键全量更新（解析+向量化所有教材） |
| `GET /admin/textbooks/status` | GET | 获取向量化整体状态 |
| `POST /admin/textbooks/generate` | POST | 根据大纲生成教材内容 |
| `GET /admin/models` | GET | 获取所有模型配置 |
| `POST /admin/models` | POST | 添加模型配置 |
| `PUT /admin/models/{model_id}` | PUT | 更新模型配置 |
| `DELETE /admin/models/{model_id}` | DELETE | 删除模型配置 |
| `POST /admin/models/{model_id}/default` | POST | 设为默认模型 |
| `GET /admin/models/default` | GET | 获取当前默认模型 |
| `GET /admin/tasks` | GET | 获取任务列表 |
| `GET /admin/tasks/{task_id}` | GET | 获取单个任务详情 |
| `DELETE /admin/tasks/{task_id}` | DELETE | 删除任务 |

完整 API 文档可在后端启动后访问：http://localhost:8000/docs

## 核心页面

| 页面 | 路径 | 说明 |
|------|------|------|
| 首页 / 年级选择 | `/` | 选择年级，浏览学科卡片 |
| AI 学习对话 | `/chat/:subject` | 与 AI 进行课文讲解、问答 |
| 随堂测验 | `/quiz` | 生成并作答针对性练习题 |
| 管理后台 | `/admin` | 教材管理、任务中心、模型接入配置 |

## 开发指南

### 添加新学科

1. 在 `textbook/` 下添加教材 Markdown 文件（命名格式：`{版本}{年份}{年级}{学期}{学科}_{内容类型}.md`）
2. 在 `backend/data/subjects/manifest.json` 中添加学科元数据
3. 通过管理后台「一键全量更新」或手动运行 `python scripts/ingest_textbooks.py` 导入向量库

### 添加新年级

1. 准备对应年级的教材 Markdown 文件
2. 在 `backend/data/subjects/manifest.json` 中添加年级信息
3. 通过管理后台执行一键全量更新

## ⚠️ Embedding 模型配置警告

### 为什么 Embedding 模型不能随意切换？

本系统采用 **RAG（检索增强生成）** 架构，教材内容在导入时通过 Embedding 模型转换为高维向量，存储在 ChromaDB 中。后续用户提问时，同样使用该模型将问题向量化，然后在向量库中搜索语义最相似的教材片段。

**核心原则：写入和查询必须使用同一个 Embedding 模型，否则语义搜索将完全失效。**

### 切换 Embedding 模型的风险

| 风险 | 说明 |
|------|------|
| **向量空间不兼容** | 不同模型（如 OpenAI `text-embedding-3-small` vs. BGE-large）将文本映射到完全不同的向量空间，彼此间不存在可比性 |
| **维度不匹配** | ChromaDB 的 Collection 维度在创建时固定，新模型若维度不同，插入/查询将直接报错 |
| **搜索结果错乱** | 即使维度相同，混合使用不同模型的向量会导致检索结果完全不可靠，AI 回答偏离教材内容 |
| **语义编码差异** | 不同模型对同一文本的语义编码方式不同，中文优化模型 vs. 通用模型在教材检索上表现差异显著 |

### 正确的模型配置策略

本系统采用 **"Embedding 固定 + LLM 灵活切换"** 的双层策略：

```
Embedding 模型（固定，.env 配置） ──→ ChromaDB（知识库）
        ↑                                  ↓
   向量化教材                        语义检索 Top-K
        ↑                                  ↓
   用户提问  ──→  LLM 对话模型（UI 灵活切换）──→ 生成回答
```

| 模型类型 | 配置位置 | 是否可热切换 | 切换影响 |
|----------|----------|-------------|----------|
| **Embedding 模型** | `.env` 的 `EMBEDDING_MODEL` | ❌ 不可 | 必须清空向量库并重新向量化全部教材 |
| **LLM 对话模型** | 前端「模型接入管理」 | ✅ 可以 | 仅影响回答生成风格，不影响知识检索 |

- **Embedding 模型**：由 `.env` 固定配置，项目初始化时选定后不建议变更
- **LLM 对话模型**：可通过前端「模型接入管理」自由添加、编辑、切换，不影响知识库检索质量

### 如果必须更换 Embedding 模型

若因业务需要确实要更换 Embedding 模型，必须执行以下操作：

1. **停止服务**
2. **清空向量库**：删除 `backend/chroma_db/` 目录下的相关 Collection 数据
3. **修改 `.env`**：更新 `EMBEDDING_MODEL` 为新的模型名称
4. **重新向量化**：通过管理后台的「一键全量更新」功能，或手动运行：
   ```bash
   cd backend
   python scripts/ingest_textbooks.py
   ```
5. **验证**：向量化完成后，进行问答测试，确认检索结果正常

> ⚠️ **警告**：未完成重新向量化前，切勿启动服务供用户使用，否则所有知识问答都将返回错误结果。

## 常见问题

**Q: 启动后前端无法连接后端？**

检查 `.env` 中的 `BACKEND_PORT` 是否与后端实际启动端口一致，并确认后端 CORS 配置允许前端地址。

**Q: AI 回答与教材无关？**

确认已执行 `python scripts/ingest_textbooks.py` 导入教材数据，并检查 `backend/chroma_db/` 目录是否存在有效数据。

**Q: 支持其他年级吗？**

代码层面已支持六到九年级扩展，只需准备对应教材数据并执行导入即可。

**Q: 如何更换 LLM 模型？**

无需修改 `.env`，直接在前端「管理后台」->「模型接入管理」中添加或编辑模型配置，并设为默认即可。LLM 模型切换不会影响知识检索。

## 许可证

MIT License
