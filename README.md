# 中学伴学助教

基于 RAG（检索增强生成）的中学多课程 AI 学习智能体，覆盖语文、数学、英语、科学、社会五门学科，为学生提供教材知识问答、课文讲解、随堂测验等个性化学习辅导。

## 功能特性

- **多学科覆盖**：语文（部编版）、数学（浙教版）、英语（人教PEP版）、科学（浙教版）、社会（人教版）
- **AI 知识问答**：基于教材内容的 RAG 检索，回答与课本相关的问题
- **课文讲解**：自动加载课文原文，AI 逐段讲解重点难点
- **随堂测验**：AI 根据当前章节生成选择题、填空题、简答题
- **章节导航**：按年级 -> 学科 -> 单元 -> 课文的层级结构浏览教材
- **流式响应**：AI 回答采用流式输出，响应更快更自然

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
```

### 前端技术栈

- [Vue 3](https://vuejs.org/) + [Vite](https://vitejs.dev/) + [TypeScript](https://www.typescriptlang.org/)
- [Element Plus](https://element-plus.org/) UI 组件库
- [Pinia](https://pinia.vuejs.org/) 状态管理
- [Vue Router](https://router.vuejs.org/) 路由
- [Markdown-it](https://github.com/markdown-it/markdown-it) + [KaTeX](https://katex.org/) 内容渲染

### 后端技术栈

- [FastAPI](https://fastapi.tiangolo.com/) Web 框架
- [ChromaDB](https://www.trychroma.com/) 向量数据库（教材知识库）
- [LangChain](https://www.langchain.com/) + [LangGraph](https://langchain-ai.github.io/langgraph/) AI Agent 编排
- [OpenAI](https://platform.openai.com/) 兼容 API（支持第三方 LLM 平台）

## 项目结构

```
.
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── api/               # API 路由（health / subjects / chat）
│   │   ├── core/              # 配置、常量
│   │   ├── models/            # Pydantic 数据模型
│   │   ├── services/          # 业务逻辑（RAG、教学 Agent）
│   │   └── utils/             # 工具函数
│   ├── chroma_db/             # 向量数据库持久化目录
│   ├── scripts/               # 数据导入脚本
│   └── requirements.txt       # Python 依赖
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── api/               # HTTP 客户端封装
│   │   ├── components/        # 公共组件
│   │   ├── stores/            # Pinia 状态管理
│   │   └── views/             # 页面视图
│   └── package.json           # Node.js 依赖
├── textbook/                   # 教材原文 Markdown
├── start.py                    # 一键启动脚本
├── .env                        # 环境变量配置
└── .env.example                # 环境变量示例
```

## 快速开始

### 环境要求

- Python 3.10+
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
| `EMBEDDING_MODEL` | 否 | 嵌入模型名称 | `text-embedding-3-small` |
| `BACKEND_PORT` | 否 | 后端端口（默认 8000） | `8000` |
| `FRONTEND_PORT` | 否 | 前端端口（默认 5173） | `5173` |
| `DEBUG` | 否 | 调试模式（默认 False） | `False` |

> 支持任何 OpenAI 兼容格式的 LLM 平台，如 [SiliconFlow](https://siliconflow.cn/)、[DashScope](https://dashscope.aliyun.com/) 等。

### 3. 安装依赖

**后端（Python）**

```bash
# 如果使用 Conda
conda activate learn
# 或使用系统 Python
pip install -r backend/requirements.txt
```

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
| `uvicorn app.main:app --reload` | 开发模式启动（热重载） |
| `python -m uvicorn app.main:app --host 0.0.0.0` | 生产模式启动 |

## 教材数据

教材原文存放于 `textbook/` 目录，按 Markdown 格式组织：

| 文件 | 学科 | 版本 | 年级 |
|------|------|------|------|
| `部编版2024七年级上册语文_完整教材内容.md` | 语文 | 部编版 | 七年级上册 |
| `浙教版2024七年级上册数学_完整教材内容.md` | 数学 | 浙教版 | 七年级上册 |
| `人教PEP版2024七年级上册英语_完整教材内容.md` | 英语 | 人教PEP版 | 七年级上册 |
| `浙教版2024七年级上册科学_完整教材内容.md` | 科学 | 浙教版 | 七年级上册 |
| `人教版2024七年级上册社会_教材梳理知识库.md` | 社会 | 人教版 | 七年级上册 |

### 导入教材到向量库

首次部署或教材更新后，执行导入脚本：

```bash
cd backend
python scripts/ingest_textbooks.py
```

该脚本会将 `textbook/` 下的 Markdown 文件切分并向量化，存入 `backend/chroma_db/`。

## API 接口

后端提供以下 RESTful API：

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /` | - | 服务根路径，返回基本信息 |
| `GET /health` | - | 健康检查 |
| `GET /subjects` | GET | 获取所有学科列表 |
| `GET /subjects/{subject_id}/chapters` | GET | 获取某学科的章节列表 |
| `GET /subjects/{subject_id}/chapters/{chapter_id}/lessons` | GET | 获取某章节下的课文/课时列表 |
| `GET /subjects/{subject_id}/lessons/{lesson_id}/content` | GET | 获取某课文的原文内容 |
| `POST /chat` | POST | AI 对话（流式 SSE） |
| `POST /quiz/generate` | POST | 生成测验题目（流式 SSE） |

完整 API 文档可在后端启动后访问：http://localhost:8000/docs

## 核心页面

| 页面 | 路径 | 说明 |
|------|------|------|
| 首页 / 年级选择 | `/` | 选择年级，浏览学科卡片 |
| AI 学习对话 | `/chat/:subject` | 与 AI 进行课文讲解、问答 |
| 随堂测验 | `/quiz` | 生成并作答针对性练习题 |

## 开发指南

### 添加新学科

1. 在 `textbook/` 下添加教材 Markdown 文件（命名格式：`{版本}{年份}{年级}上册{学科}_{内容类型}.md`）
2. 在 `backend/app/api/subjects.py` 的 `_SUBJECTS_BASE` 列表中添加学科元数据
3. 运行 `python scripts/ingest_textbooks.py` 导入向量库

### 添加新年级

1. 准备对应年级的教材 Markdown 文件
2. 在 `subjects.py` 的 `_GRADES` 列表中添加年级
3. 运行导入脚本

## 常见问题

**Q: 启动后前端无法连接后端？**

检查 `.env` 中的 `BACKEND_PORT` 是否与后端实际启动端口一致，并确认后端 CORS 配置允许前端地址。

**Q: AI 回答与教材无关？**

确认已执行 `python scripts/ingest_textbooks.py` 导入教材数据，并检查 `backend/chroma_db/` 目录是否存在有效数据。

**Q: 支持其他年级吗？**

代码层面已支持六到九年级扩展，只需准备对应教材数据并执行导入即可。

## 许可证

MIT License
