<template>
  <div class="chat-window" :class="{ 'sidebar-collapsed': store.sidebarCollapsed }">
    <div class="chat-header">
      <button class="menu-btn" @click="onMenuClick()">
        <el-icon size="18"><Menu /></el-icon>
      </button>
      <div v-if="currentSubject" class="header-context">
        <div
          class="subject-badge"
          :style="{ background: subjectColor, color: '#fff' }"
        >
          {{ currentSubject.name.slice(0, 2) }}
        </div>
        <div class="header-text">
          <span v-if="currentLesson" class="chapter-name">{{ currentSubject.grade }} > {{ currentLesson.name }}</span>
          <span v-else-if="currentChapter" class="chapter-name">{{ currentSubject.grade }} > {{ currentChapter.name }}</span>
        </div>
      </div>
      <div v-else class="no-context">
        <el-icon size="16"><InfoFilled /></el-icon>
        <span>请先选择一门课程</span>
      </div>
      <button class="home-btn" @click="goHome">
        <el-icon size="14"><ArrowLeft /></el-icon>
        <span>返回</span>
      </button>
    </div>

    <div class="chat-messages" ref="msgRef">
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        class="message-row"
        :class="msg.role"
      >
        <div class="avatar" :class="msg.role">
          <el-icon v-if="msg.role === 'assistant'" size="18"><ChatDotRound /></el-icon>
          <span v-else>我</span>
        </div>
        <div class="message-body">
          <div class="bubble" :class="msg.role">
            <MarkdownRenderer v-if="msg.role === 'assistant'" :source="msg.content" />
            <div v-else class="plain-text">{{ msg.content }}</div>
          </div>
          <div v-if="msg.references?.length" class="references">
            <div class="references-title">📚 教材出处</div>
            <div v-for="(ref, i) in msg.references" :key="i" class="reference-item">
              <span class="reference-lesson">{{ ref.lesson }}</span>
              <span v-if="ref.chapter" class="reference-meta">{{ ref.chapter }}</span>
              <span v-if="ref.grade" class="reference-meta">{{ ref.grade }}{{ ref.semester || '' }}</span>
            </div>
          </div>
          <div v-if="msg.suggested_actions?.length" class="actions">
            <button
              v-for="act in msg.suggested_actions"
              :key="act"
              class="action-chip"
              @click="sendMessage(act)"
            >
              {{ act }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="loading" class="message-row assistant">
        <div class="avatar assistant">
          <el-icon size="18"><ChatDotRound /></el-icon>
        </div>
        <div class="bubble assistant loading">
          <span class="dot"></span>
          <span class="dot"></span>
          <span class="dot"></span>
        </div>
      </div>
    </div>

    <div class="chat-input-area">
      <div class="quick-actions">
        <button class="quick-btn" @click="loadLessonContent">
          <el-icon size="14"><Document /></el-icon>
          <span>课文原文</span>
        </button>
        <button class="quick-btn" @click="sendMessage('给我讲解这个单元')">
          <el-icon size="14"><Reading /></el-icon>
          <span>讲解</span>
        </button>
        <button class="quick-btn" @click="sendMessage('出道题考考我')">
          <el-icon size="14"><EditPen /></el-icon>
          <span>出题</span>
        </button>
        <button class="quick-btn" @click="sendMessage('总结一下重点')">
          <el-icon size="14"><Memo /></el-icon>
          <span>总结</span>
        </button>
        <button class="quick-btn" @click="goQuiz">
          <el-icon size="14"><DocumentChecked /></el-icon>
          <span>测验</span>
        </button>
      </div>
      <div class="input-row">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          placeholder="输入问题，或点击上方快捷操作..."
          @keydown.enter.prevent="sendMessage(input)"
          resize="none"
        />
        <button
          class="send-btn"
          :class="{ show: input.trim() && !loading }"
          :disabled="!input.trim() || loading"
          @click="sendMessage(input)"
          title="发送"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app'
import { chatApi, subjectApi, getSessionId, setSessionId, clearSessionId } from '../api/client'
import type { Reference } from '../api/client'
import { ChatDotRound, InfoFilled, Reading, EditPen, Memo, DocumentChecked, Document, ArrowLeft, Menu } from '@element-plus/icons-vue'
import MarkdownRenderer from './MarkdownRenderer.vue'

const router = useRouter()
const store = useAppStore()
const currentSubject = computed(() => store.currentSubject)
const currentChapter = computed(() => store.currentChapter)
const currentLesson = computed(() => store.currentLesson)

// 切换课程即开启新会话：checkpointer 按 session_id 续接记忆，
// 不复位会把上一门课的对话历史带进新课程（跨课串味）
watch(() => currentSubject.value?.id, (newId, oldId) => {
  if (newId !== oldId) clearSessionId()
})

function onMenuClick() {
  if (store.isMobile) {
    store.toggleSidebar()
  } else {
    store.toggleSidebarCollapse()
  }
}

const subjectColor = computed(() => {
  const map: Record<string, string> = {
    chinese: 'var(--subject-chinese)',
    math: 'var(--subject-math)',
    english: 'var(--subject-english)',
    science: 'var(--subject-science)',
    social: 'var(--subject-social)',
  }
  const baseId = currentSubject.value?.id.split('_')[0]
  return baseId ? map[baseId] || 'var(--accent-primary)' : 'var(--accent-primary)'
})

const input = ref('')
const loading = ref(false)
const messages = ref<Array<{
  role: string
  content: string
  suggested_actions?: string[]
  references?: Reference[]
}>>([
  {
    role: 'assistant',
    content: '你好！我是你的AI学习助手。选择左侧的课程和章节，就可以开始学习了。你可以问我任何问题，比如"给我讲解这个单元"、"出道题考考我"或者"总结一下重点"。',
    suggested_actions: ['给我讲解这个单元', '出道题考考我', '总结一下重点'],
  },
])

const msgRef = ref<HTMLDivElement>()

async function sendMessage(text: string) {
  if (!text.trim() || loading.value) return
  if (!currentSubject.value) {
    messages.value.push({ role: 'assistant', content: '请先从首页选择一门课程哦～' })
    await scrollBottom()
    return
  }

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true
  await scrollBottom()

  let assistantIdx = -1
  // references 事件先于首个 token 到达（气泡尚未创建），先暂存，气泡创建时挂上
  let pendingReferences: Reference[] = []

  try {
    await chatApi.sendStream(
      {
        message: text,
        subject: currentSubject.value?.id,
        chapter: currentChapter.value?.id,
        lesson: currentLesson.value?.id,
        session_id: getSessionId() || undefined,
      },
      {
        onToken: (token: string) => {
          if (assistantIdx === -1) {
            messages.value.push({ role: 'assistant', content: token, suggested_actions: [], references: pendingReferences })
            assistantIdx = messages.value.length - 1
            loading.value = false
          } else {
            messages.value[assistantIdx].content += token
          }
          scrollBottom()
        },
        onReferences: (references: Reference[]) => {
          pendingReferences = references
          if (assistantIdx !== -1) {
            messages.value[assistantIdx].references = references
          }
        },
        onDone: ({ reply, actions, references, sessionId }) => {
          if (sessionId) setSessionId(sessionId)
          // 兜底：全程未收到 token（如模型不产生流式事件）但 done 携带完整答复时，补建气泡
          if (assistantIdx === -1 && reply) {
            messages.value.push({ role: 'assistant', content: reply, suggested_actions: actions, references: references?.length ? references : pendingReferences })
          } else if (assistantIdx !== -1) {
            messages.value[assistantIdx].content = reply
            messages.value[assistantIdx].suggested_actions = actions
            if (references?.length) {
              messages.value[assistantIdx].references = references
            }
          }
          loading.value = false
          scrollBottom()
        },
        onError: (_err: string) => {
          if (assistantIdx !== -1) {
            messages.value[assistantIdx].content = '抱歉，服务器暂时响应不过来，请稍后再试。'
          } else {
            messages.value.push({ role: 'assistant', content: '抱歉，服务器暂时响应不过来，请稍后再试。' })
          }
          loading.value = false
          scrollBottom()
        },
      },
    )
  } catch (e) {
    if (assistantIdx !== -1) {
      messages.value[assistantIdx].content = '抱歉，服务器暂时响应不过来，请稍后再试。'
    } else {
      messages.value.push({ role: 'assistant', content: '抱歉，服务器暂时响应不过来，请稍后再试。' })
    }
    loading.value = false
    await scrollBottom()
  }
}

async function scrollBottom() {
  await nextTick()
  if (msgRef.value) {
    msgRef.value.scrollTop = msgRef.value.scrollHeight
  }
}

function goQuiz() {
  if (!currentSubject.value) {
    messages.value.push({ role: 'assistant', content: '请先从首页选择一门课程哦～' })
    return
  }
  router.push({ name: 'quiz' })
}

function goHome() {
  const grade = currentSubject.value?.grade
  if (grade) {
    router.push({ path: '/', query: { grade } })
  } else {
    router.push('/')
  }
}

async function loadLessonContent() {
  if (!currentSubject.value || !currentLesson.value) {
    messages.value.push({ role: 'assistant', content: '请先从左侧选择一篇具体的课文哦～' })
    return
  }
  loading.value = true
  await scrollBottom()
  try {
    const { data } = await subjectApi.lessonContent(currentSubject.value.id, currentLesson.value.id)
    messages.value.push({
      role: 'assistant',
      content: `## ${data.lesson_name}\n\n${data.content}`,
      suggested_actions: [],
    })
  } catch (e: any) {
    const msg = e?.response?.data?.detail || '获取课文原文失败，请稍后再试'
    messages.value.push({ role: 'assistant', content: msg })
  } finally {
    loading.value = false
    await scrollBottom()
  }
}
</script>

<style scoped>
.chat-window {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.chat-header {
  padding: var(--space-2) var(--space-4);
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
}
.header-context {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.subject-badge {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: 700;
  flex-shrink: 0;
}
.header-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.subject-name {
  font-weight: 600;
  font-size: var(--text-base);
  color: var(--text-primary);
}
.chapter-name {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.no-context {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}
.menu-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-light);
  background: var(--bg-base);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}
.chat-window.sidebar-collapsed .menu-btn {
  display: flex;
}
.menu-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--border-medium);
}
.home-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-light);
  background: var(--bg-base);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  margin-left: auto;
}
.home-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--border-medium);
}

@media (max-width: 768px) {
  .menu-btn {
    display: flex;
  }
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5) var(--space-6);
  background: var(--bg-base);
}
.message-row {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
  align-items: flex-start;
}
.message-row.user {
  flex-direction: row-reverse;
}
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: var(--text-xs);
  font-weight: 600;
}
.avatar.assistant {
  background: var(--accent-primary);
  color: var(--text-inverse);
}
.avatar.user {
  background: var(--bg-hover);
  color: var(--text-secondary);
  border: 1px solid var(--border-light);
}
.message-body {
  max-width: 70%;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
@media (max-width: 768px) {
  .message-body {
    max-width: 88%;
  }
}
.bubble {
  padding: var(--space-4) var(--space-5);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  font-size: var(--text-md);
  line-height: 1.7;
}
.bubble.assistant {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border-light);
  border-top-left-radius: var(--space-1);
}
.bubble.user {
  background: var(--accent-primary);
  color: var(--text-inverse);
  border-top-right-radius: var(--space-1);
}
.plain-text {
  white-space: pre-wrap;
}

.bubble.loading {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-4) var(--space-5);
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-tertiary);
  animation: bounce 1.4s infinite ease-in-out both;
}
.dot:nth-child(1) { animation-delay: -0.32s; }
.dot:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

.actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.references {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
}
.references-title {
  color: var(--text-tertiary);
  font-weight: 600;
  margin-bottom: var(--space-1);
}
.reference-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 2px 0;
  flex-wrap: wrap;
}
.reference-lesson {
  color: var(--accent-primary);
  font-weight: 500;
}
.reference-meta {
  color: var(--text-tertiary);
}
.action-chip {
  padding: var(--space-1) var(--space-3);
  border-radius: 100px;
  border: 1px solid var(--border-light);
  background: var(--bg-card);
  color: var(--accent-primary);
  font-size: var(--text-xs);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.action-chip:hover {
  background: var(--accent-primary-light);
  border-color: var(--accent-primary);
}

.chat-input-area {
  padding: var(--space-4) var(--space-6) var(--space-5);
  background: var(--bg-card);
  border-top: 1px solid var(--border-light);
  flex-shrink: 0;
}
.quick-actions {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.quick-btn {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-light);
  background: var(--bg-base);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.quick-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--border-medium);
}
.input-row {
  display: flex;
  gap: var(--space-3);
  align-items: center;
}
.input-row :deep(.el-textarea__inner) {
  border-radius: var(--radius-md);
  resize: none;
  font-size: var(--text-md);
  padding: var(--space-3) var(--space-4);
}
.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  cursor: pointer;
  background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary, var(--accent-primary)) 100%);
  color: #fff;
  box-shadow: 0 2px 10px color-mix(in srgb, var(--accent-primary) 30%, transparent);
  opacity: 0;
  transform: scale(0.8);
  pointer-events: none;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.send-btn.show {
  opacity: 1;
  transform: scale(1);
  pointer-events: auto;
}
.send-btn:hover:not(:disabled) {
  transform: scale(1.08);
  box-shadow: 0 4px 16px color-mix(in srgb, var(--accent-primary) 40%, transparent);
}
.send-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
</style>
