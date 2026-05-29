import axios from 'axios'

declare const __API_BASE_URL__: string

const api = axios.create({
  baseURL: __API_BASE_URL__,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

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
  history?: Array<{role: string; content: string}>
}

export interface ChatResp {
  reply: string
  intent?: string
  references?: Array<Record<string, unknown>>
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

  sendStream: (
    data: ChatReq,
    onToken: (token: string) => void,
    onDone: (reply: string, actions: string[]) => void,
    onError: (err: string) => void,
  ) => {
    return fetch(`${api.defaults.baseURL}/chat/stream`, {
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
              onDone(payload.reply, payload.suggested_actions)
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
}

export const adminApi = {
  listTextbooks: () => api.get<TextbookItem[]>('/admin/textbooks'),
  parse: (filename: string) => api.post('/admin/textbooks/parse', { filename }),
  ingest: (filename: string) => api.post<{ task_id: string; status: string; message: string }>('/admin/textbooks/ingest', { filename }),
  getTask: (taskId: string) => api.get<TaskInfo>(`/admin/tasks/${taskId}`),
}

export const quizApi = {
  generate: (data: QuizReq) => api.post<QuizResp>('/chat/quiz', data),

  generateStream: (
    data: QuizReq,
    onToken: (token: string) => void,
    onDone: (question: string, options: string[] | null, correctAnswer: string, explanation: string, knowledgePoint: string) => void,
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
              onDone(payload.question, payload.options, payload.correct_answer, payload.explanation, payload.knowledge_point)
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
