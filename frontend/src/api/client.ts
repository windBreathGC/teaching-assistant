import axios from 'axios'

declare const __API_BASE_URL__: string

// ── 管理后台令牌（对应后端 X-Admin-Token 校验）──
const ADMIN_TOKEN_KEY = 'admin_token'

export function getAdminToken(): string {
  return localStorage.getItem(ADMIN_TOKEN_KEY) || ''
}

export function setAdminToken(token: string): void {
  localStorage.setItem(ADMIN_TOKEN_KEY, token)
}

export function clearAdminToken(): void {
  localStorage.removeItem(ADMIN_TOKEN_KEY)
}

// ── 对话会话ID（对应后端 checkpointer 的 thread_id，支撑多轮记忆）──
const SESSION_ID_KEY = 'chat_session_id'

export function getSessionId(): string {
  return localStorage.getItem(SESSION_ID_KEY) || ''
}

export function setSessionId(id: string): void {
  if (id) localStorage.setItem(SESSION_ID_KEY, id)
}

export function clearSessionId(): void {
  localStorage.removeItem(SESSION_ID_KEY)
}

const api = axios.create({
  baseURL: __API_BASE_URL__,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截：/admin/* 请求自动附带管理令牌
api.interceptors.request.use((config) => {
  if (config.url?.startsWith('/admin')) {
    const token = getAdminToken()
    if (token) {
      config.headers['X-Admin-Token'] = token
    }
  }
  return config
})

// 响应拦截：管理接口 401 时清除失效令牌并通知界面重新录入
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && error.config?.url?.startsWith('/admin')) {
      clearAdminToken()
      window.dispatchEvent(new CustomEvent('admin-token-required'))
    }
    return Promise.reject(error)
  },
)

export interface Subject {
  id: string
  name: string
  publisher: string
  version: string
  grade: string
  description: string
}

export interface Chapter {
  id: string
  name: string
  subject_id: string
  description?: string
}

export interface Lesson {
  id: string
  name: string
  chapter_id: string
  content_type?: string
}

export interface LessonContent {
  lesson_id: string
  lesson_name: string
  content: string
}

export interface ChatReq {
  message: string
  subject?: string
  chapter?: string
  lesson?: string
  session_id?: string
}

export interface Reference {
  lesson?: string
  chapter?: string
  subject?: string
  grade?: string
  semester?: string
  snippet?: string
  score?: number
}

export interface ChatResp {
  reply: string
  intent?: string
  session_id?: string
  references?: Reference[]
  suggested_actions?: string[]
}

export interface QuizReq {
  subject: string
  chapter?: string
  lesson?: string
  difficulty: '基础' | '提高' | '拓展'
  question_type: '选择' | '填空' | '简答'
}

export interface QuizResp {
  question: string
  options: string[] | null
  correct_answer: string
  explanation: string
  knowledge_point: string
  quiz_id?: string | null
}

export interface Mastery {
  knowledge_point: string
  mastery: number
  total_attempts: number
  correct_attempts: number
}

export interface QuizGradeResp {
  quiz_id: string
  is_correct: boolean
  correct_answer: string
  explanation: string
  diagnosis: string
  misconception: string | null
  knowledge_point: string
  mastery?: Mastery | null
}

// 流式对话的回调集合：token 增量 / done 权威结果 / error / references 教材出处
export interface ChatStreamHandlers {
  onToken: (token: string) => void
  onDone: (payload: { reply: string; actions: string[]; references: Reference[]; sessionId: string }) => void
  onError: (err: string) => void
  onReferences?: (references: Reference[]) => void
}

// 流式出题的 done 载荷
export interface QuizStreamDone {
  question: string
  options: string[] | null
  correct_answer: string
  explanation: string
  knowledge_point: string
  quiz_id: string | null
}

export const healthApi = {
  check: () => api.get('/health'),
}

export const subjectApi = {
  list: () => api.get<Subject[]>('/subjects'),
  chapters: (subjectId: string) => api.get<Chapter[]>(`/subjects/${subjectId}/chapters`),
  lessons: (subjectId: string, chapterId: string) => api.get<Lesson[]>(`/subjects/${subjectId}/chapters/${chapterId}/lessons`),
  lessonContent: (subjectId: string, lessonId: string) => api.get<LessonContent>(`/subjects/${subjectId}/lessons/${lessonId}/content`),
}

export const chatApi = {
  send: (data: ChatReq) => api.post<ChatResp>('/chat', data),

  sendStream: (data: ChatReq, handlers: ChatStreamHandlers) => {
    const { onToken, onDone, onError, onReferences } = handlers
    return fetch(`${api.defaults.baseURL}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(async (response) => {
      if (!response.ok) {
        const text = await response.text()
        throw new Error(text)
      }
      // body是一个ReadableStream（可分块持续读取的流）对象
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (reader) {
        // 通过read()方法持续读取流数据
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        // 按照SSE协议要求，每个chunk的结尾必须是\n\n，所以可以采用\n进行分块
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          // 按照SSE协议要求，每个chunk的开头必须是 data:，所以可以采用startsWith判断
          if (line.startsWith('data: ')) {
            // 去掉头部的 data: 部分内容，正好6个字符；再解析为JSON体
            const payload = JSON.parse(line.slice(6))
            // 根据后端封装的内容结构分发：token增量 / done权威结果 / references教材出处 / error
            if (payload.type === 'token') {
              onToken(payload.content)
            } else if (payload.type === 'references') {
              onReferences?.(payload.references || [])
            } else if (payload.type === 'done') {
              onDone({
                reply: payload.reply,
                actions: payload.suggested_actions || [],
                references: payload.references || [],
                sessionId: payload.session_id || '',
              })
            } else if (payload.type === 'error') {
              onError(payload.detail)
            }
          }
        }
      }
    })
  },
}

export interface TextbookItem {
  filename: string
  subject: string
  grade: string
  semester: string
  parsed: boolean
  ingested: boolean
  outdated: boolean
  chunks: number | null
}

export interface TaskInfo {
  task_id: string
  type: string
  filename: string
  status: string
  progress: number
  message: string
  result: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface LLMConfig {
  base_url: string
  api_key: string
  model_name: string
  temperature: number
}

export interface GenerateOutlineReq {
  subject: string
  grade: string
  semester: string
  publisher: string
  version_year: string
  region: string
  notes: string
  model_id: string
}

export interface GenerateTextbookReq {
  outline: Record<string, unknown>
  subject: string
  grade: string
  semester: string
  publisher: string
  version_year: string
  region: string
  model_id: string
}

export interface ModelProvider {
  id: string
  name: string
  base_url: string
  api_key: string
  model_name: string
  temperature: number
  is_default: boolean
}

export interface AnalyzeReport {
  filename: string
  structure_valid: boolean
  has_valid_filename: boolean
  has_title: boolean
  chapter_count: number
  lesson_count: number
  total_chars: number
  avg_chars_per_chapter: number
  has_failed_sections: boolean
  subject: string | null
  warnings: string[]
  recommendations: string[]
  detail: Record<string, unknown>
  ready_for_ingest: boolean
}

export const adminApi = {
  listTextbooks: () => api.get<TextbookItem[]>('/admin/textbooks'),
  parse: (filename: string) => api.post('/admin/textbooks/parse', { filename }),
  ingest: (filename: string) => api.post<{ task_id: string; status: string; message: string }>('/admin/textbooks/ingest', { filename }),
  batchIngest: () => api.post<{ task_id: string; status: string; message: string }>('/admin/batch-ingest'),
  getTask: (taskId: string) => api.get<TaskInfo>(`/admin/tasks/${taskId}`),
  generateOutline: (data: GenerateOutlineReq) => api.post<{ status: string; task_id: string; message: string }>('/admin/generate-outline', data),
  listTasks: (params?: { skip?: number; limit?: number }) => api.get<{ tasks: TaskInfo[]; total: number }>('/admin/tasks', { params }),
  generateTextbook: (data: GenerateTextbookReq) => api.post<{ status: string; task_id: string; message: string }>('/admin/generate-textbook', data),
  analyzeTextbook: (filename: string) => api.post<{ status: string; report: AnalyzeReport }>('/admin/analyze-textbook', { filename }),
  listModels: () => api.get<{ status: string; models: ModelProvider[] }>('/admin/models'),
  addModel: (data: Omit<ModelProvider, 'id'>) => api.post<{ status: string; model: ModelProvider }>('/admin/models', data),
  updateModel: (id: string, data: Partial<Omit<ModelProvider, 'id'>>) => api.put<{ status: string; model: ModelProvider }>(`/admin/models/${id}`, data),
  deleteModel: (id: string) => api.delete<{ status: string; message: string }>(`/admin/models/${id}`),
  setDefaultModel: (id: string) => api.post<{ status: string; message: string }>(`/admin/models/${id}/default`),
}

export const quizApi = {
  generate: (data: QuizReq) => api.post<QuizResp>('/chat/quiz', data),

  // 提交答案判分：后端判分 + 错因诊断 + 掌握度更新（幂等）
  submit: (quizId: string, userAnswer: string) =>
    api.post<QuizGradeResp>('/chat/quiz/submit', { quiz_id: quizId, user_answer: userAnswer }),

  generateStream: (
    data: QuizReq,
    onToken: (token: string) => void,
    onDone: (result: QuizStreamDone) => void,
    onError: (err: string) => void,
  ) => {
    return fetch(`${api.defaults.baseURL}/chat/quiz/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(async (response) => {
      if (!response.ok) {
        const text = await response.text()
        throw new Error(text)
      }
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (reader) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const payload = JSON.parse(line.slice(6))
            if (payload.type === 'token') {
              onToken(payload.content)
            } else if (payload.type === 'done') {
              onDone({
                question: payload.question,
                options: payload.options,
                correct_answer: payload.correct_answer,
                explanation: payload.explanation,
                knowledge_point: payload.knowledge_point,
                quiz_id: payload.quiz_id || null,
              })
            } else if (payload.type === 'error') {
              onError(payload.detail)
            }
          }
        }
      }
    })
  },
}

export default api
