# 中学伴学助教 - 前端

Vue 3 单页应用（SPA），提供年级/学科浏览、AI 学习对话、随堂测验、管理后台四类页面。

> 项目整体介绍、安装与启动方式见根目录 [README.md](../README.md)；后端接口与检索/入库设计见 [backend/README.md](../backend/README.md)。本文档收录前端侧的**框架选型、目录职责与关键实现细节**。

## 技术栈

| 依赖 | 用途 |
|------|------|
| Vue 3（Composition API + `<script setup>`） | 框架 |
| Vite 8 + TypeScript 6 | 开发服务器 / 构建 |
| Vue Router 4 | 路由（history 模式） |
| Pinia 3 | 状态管理（setup 风格 store） |
| Element Plus 2（zh-cn 语言包） | UI 组件库，全量注册图标 |
| axios | 普通 JSON 接口 |
| markdown-it + KaTeX | AI 回复的 Markdown / 数学公式渲染 |

## 目录结构

```
src/
├── api/client.ts        # axios 实例 + 全部接口封装 + SSE 流式消费
├── components/          # ChatWindow（对话）、SubjectTree（章节树）、MarkdownRenderer、
│                        # ModelManager（模型接入）、TaskCenter（任务中心）
├── router/index.ts      # / → Home，/chat/:subject? → Chat，/quiz，/admin
├── stores/
│   ├── app.ts           # 学科/章节/课文数据与当前选中态、侧边栏、移动端适配
│   └── modelStore.ts    # 管理后台的模型配置 CRUD 状态
├── styles/              # vars.css（CSS 变量/学科主题色）+ global.css
├── utils/markdown.ts    # markdown-it + KaTeX 渲染管线
└── views/               # Home / Chat / Quiz / Admin 四个页面
```

## 开发服务器与代理（vite.config.ts）

开发模式是**两个服务器**：浏览器只访问 vite（5173），API 由 vite 按路径规则转发给 FastAPI（8000），对浏览器同源、免 CORS。

```
浏览器 → 5173 (vite) ── 匹配 proxy 规则 ──→ 8000 (FastAPI)
              └── 不匹配 ──→ 返回页面/静态资源
```

当前代理规则：

| 规则 | 覆盖接口 |
|------|----------|
| `^/(subjects\|health)` | 学科/章节/课文、健康检查 |
| `^/chat($\|/stream\|/quiz)` | 对话与出题（精确匹配，见下） |
| `^/admin/` | 管理后台全部接口 |

**关键坑（已修复，勿回退）**：chat 规则不能用 `^/chat` 前缀匹配——页面路由 `/chat/:subject`（如 `/chat/chinese_7a`）会被一并转发到后端，FastAPI 没有该 GET 路由，直接访问或刷新聊天页会返回 `{"detail":"Not Found"}`。必须精确匹配到具体 API 路径。

**后端新增接口时**：以 `/subjects`、`/health`、`/admin/` 开头或落在 chat 精确规则内 → 无需改动；新增其他前缀（如 `/notes`）→ 必须在此添加规则，否则开发模式 404。生产模式无此问题（FastAPI 同源托管 `dist/`，proxy 不生效）。

其他配置：

- `__API_BASE_URL__` 编译期常量：开发模式注入空字符串（走相对路径 + 代理），axios 的 `baseURL` 用它。
- `loadEnv` 从**根目录** `.env` 读取 `BACKEND_PORT` / `FRONTEND_PORT`，端口配置前后端共用一份。
- 配置文件改动**不会热更新**，修改后必须重启 `npm run dev`。

## HTTP 层设计（api/client.ts）

**axios 是项目选型，不是 Vue 的要求。** Vue 官方不内置 HTTP 客户端（对比 Angular 的官方 `HttpClient`），常见替代有原生 `fetch`、`ky`、`ofetch`、VueUse 的 `useFetch`。选 axios 的原因：

1. **拦截器**：统一注入令牌、统一处理 401（见下文「管理后台令牌」），几行代码搞定；
2. 开箱即用的 JSON 序列化/反序列化、超时、错误状态码自动 reject；
3. 生态惯性。

全部 HTTP 出口收敛在这一个文件里，将来替换实现组件层无感。

### axios 实例配置

```ts
const api = axios.create({
  baseURL: __API_BASE_URL__,  // 编译期常量（vite define 注入），当前恒为 ''
  timeout: 30000,             // 30s 无响应自动中止
  headers: { 'Content-Type': 'application/json' },
})
```

- `baseURL` 为相对路径前缀：`api.get('/subjects')` 实际请求 = `baseURL + '/subjects'`。开发模式靠 vite proxy 转发，生产模式前后端同源，因此恒为空字符串。
- 实例化（而非裸用全局 axios）的意义：拦截器只作用于本实例；配置一次处处复用。

### 为什么流式接口用原生 fetch 而不是 axios

axios 不支持对响应体逐块读取（拿不到 `ReadableStream`），SSE 必须 `response.body.getReader()`，因此 `sendStream` / `generateStream` 用原生 `fetch` 实现（见下文「SSE 流式消费」）。

**已知边界**：`timeout: 30000` 只保护 axios 实例上的普通请求；fetch 本身没有 timeout 概念（需 AbortController），两条流式请求当前**无超时保护**。

## SSE 流式消费（api/client.ts）

浏览器原生 `EventSource` 只支持 GET，而流式接口是 POST，因此用 `fetch` + `ReadableStream` 手动解析：

```
fetch(POST) → response.body.getReader()
  → 循环 read()，TextDecoder 流式解码，按 \n 切分（尾部不完整行留在 buffer）
  → 行首为 "data: " 时 JSON.parse
  → 按 payload.type 分发：token → onToken / done → onDone / error → onError
```

事件协议（`intent` / `token` / `done` / `error`）的字段约定见 backend/README 的 SSE 章节——**改协议两端必须同步改**。前端对未知事件类型静默忽略，后端新增事件类型不会破坏旧前端。

`ChatWindow.vue` 的渲染策略：`token` 事件增量追加到当前 AI 消息；`done` 事件用服务端权威全文**覆盖**本地拼接结果（防丢包/解析误差），并附着 `suggested_actions`。

## 状态管理（Pinia）

`stores/app.ts`：

- `subjects` / `chapters` / `lessons`：按需加载并缓存；`ensureSubjects()` 用**共享 Promise** 去重并发调用——深链接直达 `/chat/:subject` 时 HomeView 不挂载，由使用方自行确保数据就绪。
- `currentSubject` / `currentChapter` / `currentLesson`：当前学习上下文，切换学科会清空下级选中。
- 移动端适配：`matchMedia('(max-width: 768px)')` 监听，窄屏时侧边栏改为抽屉式。

`stores/modelStore.ts`：管理后台模型配置的列表、增删改、设为默认、编辑弹窗状态。

## 管理后台令牌

- 令牌存 `localStorage`（key: `admin_token`），对应后端 `.env` 的 `ADMIN_TOKEN`；后端未配置时管理接口放行（开发模式），前端不弹窗。
- axios 请求拦截器：`/admin/*` 请求自动附带 `X-Admin-Token` 头。
- 401 处理链路（响应拦截器 → 全局弹窗 → 页面刷新）：

```
管理接口返回 401
  → 响应拦截器清除失效令牌，派发 admin-token-required 事件
  → App.vue 全局监听：ElMessageBox.prompt 录入令牌（ModelManager /
    TaskCenter 挂在 App.vue 全局导航上，任何页面都可能触发 401，
    因此弹窗必须在 App.vue 而不是 AdminView）
  → 保存后派发 admin-token-saved 事件
  → AdminView 监听该事件并重新加载数据
```

## 深链接直达 /chat/:subject 的数据就绪

学科列表原本只在 HomeView 挂载时加载，直接在 `/chat/:subject` 刷新页面时 HomeView 不挂载、`subjectMap` 为空，SubjectTree 的路由 watcher 静默跳过 → 侧边栏空白、ChatWindow 也无法发送消息（`currentSubject` 为 null）。

修复方案（stores/app.ts 的 `ensureSubjects()`）：

- 已加载则直接返回；并发调用共享同一个 Promise 去重；失败后重置 Promise 允许下次重试；
- SubjectTree 的路由 watcher 发现 `subjectMap` 查不到时，先 `await store.ensureSubjects()` 再查找学科。

修复后刷新 `/chat/chinese_7a` 的请求序列：`GET /subjects`（兜底加载）→ `GET /subjects/chinese_7a/chapters` → 侧边栏正常渲染，ChatWindow 因 `currentSubject` 就绪一并恢复。

## Markdown / 公式渲染（utils/markdown.ts + MarkdownRenderer.vue）

`renderMarkdown` 的渲染管线（顺序敏感，改动时注意）：

```
原始文本
  → 1. 代码块（``` 与行内 `）替换为占位符保护起来
  → 2. 剩余文本做 KaTeX 渲染（$$...$$ 块级 / $...$ 行内，throwOnError: false，
       单个公式错误降级为 .katex-error 提示块，不影响整篇）
  → 3. markdown-it 渲染（html: false 禁内嵌 HTML 防注入、linkify、breaks、typographer）
  → 4. 代码块单独经 md.render 渲染后替换回占位符
```

这样设计是为了让 KaTeX 和代码块互不干扰（代码里的 `$` 不会被当公式）。`MarkdownRenderer.vue` 用 `computed` 缓存渲染结果，`v-html` 输出，样式引入 `katex.min.css`。

> 注：`codePlaceholder` 使用 Unicode 私用区字符（U+E000）包裹，避免与正文内容冲突（历史实现用 NUL 字符，会导致文件被识别为二进制、编辑器无法正常打开）。

## 路由与页面

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | HomeView | 年级选择、学科卡片 |
| `/chat/:subject?` | ChatView | 左侧 SubjectTree + 右侧 ChatWindow |
| `/quiz` | QuizView | 随堂测验（流式出题、作答、解析） |
| `/admin` | AdminView | 教材管理、任务中心、模型接入 |

路由用 history 模式：开发模式由 vite 兜底返回 `index.html`；生产模式 FastAPI 的 `StaticFiles` 无 SPA 回退，直接访问/刷新子路径会 404（根 README 已说明访问入口为首页）。

## 附录：Angular 背景读者的概念速查

本项目全部使用 Vue 3 组合式 API（`<script setup>`）。与 Angular 常用概念的对应关系：

| Angular | 本项目中的 Vue 对应 | 示例位置 |
|---------|--------------------|----------|
| `ngOnChanges`（含初始化触发） | `watch(..., { immediate: true })`（Vue 的 watch 默认**不含**首次触发，需显式 immediate） | SubjectTree.vue 路由 watcher |
| `ngAfterViewInit` | `onMounted`（DOM 就绪后才能操作 DOM/注册监听） | AdminView.vue |
| `ngOnDestroy` | `onUnmounted`（移除监听、断开 Observer，防内存泄漏） | AdminView.vue / App.vue |
| `@Input()` | `defineProps()` | — |
| `@Output() EventEmitter` | `defineEmits()` + `emit()` | — |
| `@Injectable` 全局服务 | Pinia store（`useAppStore()` 一行"注入"） | stores/app.ts |
| 局部服务注入 | `provide` / `inject`（本项目未用，统一走 Pinia） | — |
| `ActivatedRoute.snapshot.params` | `useRoute().params` + `watch` 响应变化 | SubjectTree.vue |
| `HTTP_INTERCEPTORS` | axios 实例的 `interceptors.request/response` | api/client.ts |

页面间传参的实践约定：**路由参数（URL）承载"页面级"参数**（如 `/chat/:subject`，可刷新可分享），**Pinia store 承载跨组件共享状态**（学科列表、当前选中态），父子组件小范围传值才用 `props/emit`。
