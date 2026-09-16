<template>
  <div class="quiz-view">
    <aside class="sidebar" :class="{ 'mobile-open': store.sidebarVisible }">
      <SubjectTree />
    </aside>
    <div
      v-if="store.sidebarVisible"
      class="sidebar-overlay"
      @click="store.closeSidebar()"
    />
    <main class="quiz-main">
      <div class="quiz-container">
        <div class="quiz-header">
          <button class="menu-btn" @click="store.toggleSidebar()">
            <el-icon size="18"><Menu /></el-icon>
          </button>
          <div class="quiz-header-main">
            <h1>
              <el-icon size="24"><EditPen /></el-icon>
              随堂测验
            </h1>
            <p class="quiz-desc">选择难度和题型，AI 将为你生成针对性练习题</p>
          </div>
          <el-button text class="back-btn" @click="$router.push({ name: 'chat' })">
            返回聊天
          </el-button>
        </div>

        <div class="quiz-config">
          <div class="config-row">
            <div class="config-item">
              <label>当前课程</label>
              <div class="config-value" :class="currentSubject?.id.split('_')[0]"
                >{{ currentSubject?.name || '未选择' }}</div
              >
            </div>
            <div class="config-item">
              <label>当前章节</label>
              <div class="config-value">{{ currentChapter?.name || '未选择' }}</div>
            </div>
            <div class="config-item">
              <label>当前课文</label>
              <div class="config-value">{{ currentLesson?.name || '未选择' }}</div>
            </div>
          </div>

          <div class="config-row">
            <div class="config-item">
              <label>难度</label>
              <div class="config-options">
                <button
                  v-for="d in difficulties"
                  :key="d"
                  class="option-btn"
                  :class="{ active: difficulty === d }"
                  @click="difficulty = d"
                >
                  {{ d }}
                </button>
              </div>
            </div>
            <div class="config-item">
              <label>题型</label>
              <div class="config-options">
                <button
                  v-for="t in questionTypes"
                  :key="t"
                  class="option-btn"
                  :class="{ active: questionType === t }"
                  @click="questionType = t"
                >
                  {{ t }}
                </button>
              </div>
            </div>
          </div>

          <el-button
            type="primary"
            size="large"
            class="generate-btn"
            :loading="generating"
            :disabled="!currentSubject"
            @click="generateQuiz"
          >
            <el-icon size="18"><MagicStick /></el-icon>
            <span>生成题目</span>
          </el-button>
        </div>

        <div v-if="quiz" class="quiz-card">
          <div class="quiz-tag">{{ difficulty }} · {{ questionType }}</div>
          <div class="quiz-question">
            <MarkdownRenderer :source="quiz.question" />
          </div>

          <div v-if="quiz.options" class="quiz-options">
            <div
              v-for="(opt, idx) in quiz.options"
              :key="idx"
              class="option-item"
              :class="{ selected: selectedOption === idx, correct: revealed && isCorrectOption(idx), wrong: revealed && selectedOption === idx && !isCorrectOption(idx) }"
              @click="!revealed && (selectedOption = idx)"
            >
              <span class="option-label">{{ String.fromCharCode(65 + idx) }}</span>
              <span class="option-text">{{ opt }}</span>
            </div>
          </div>

          <div v-else class="quiz-answer-input">
            <el-input
              v-model="userAnswer"
              type="textarea"
              :rows="3"
              placeholder="请输入你的答案..."
              :disabled="revealed"
            />
          </div>

          <div class="quiz-actions">
            <el-button
              v-if="!revealed"
              type="primary"
              :loading="submitting"
              :disabled="quiz.options ? selectedOption === null : !userAnswer.trim()"
              @click="revealAnswer"
            >
              {{ submitting ? '判分中...' : '提交答案' }}
            </el-button>
            <el-button v-else type="success" @click="generateQuiz">
              再来一题
            </el-button>
          </div>

          <div v-if="revealed" class="quiz-explanation">
            <div class="explanation-header">
              <el-icon size="18" :class="isCorrect ? 'icon-correct' : 'icon-wrong'"><CircleCheck v-if="isCorrect" /><CircleClose v-else /></el-icon>
              <span :class="isCorrect ? 'text-correct' : 'text-wrong'">
                {{ isCorrect ? '回答正确！' : '回答错误' }}
              </span>
              <span v-if="gradeResult?.misconception" class="misconception-chip">
                {{ gradeResult.misconception }}
              </span>
            </div>
            <div class="correct-answer">
              <strong>正确答案：</strong>{{ quiz.correct_answer }}
            </div>
            <div v-if="gradeResult?.diagnosis" class="diagnosis">
              <strong>错因诊断：</strong>{{ gradeResult.diagnosis }}
            </div>
            <div class="explanation-body">
              <MarkdownRenderer :source="quiz.explanation" />
            </div>
            <div class="knowledge-point">
              <el-icon size="14"><Collection /></el-icon>
              <span>知识点：{{ quiz.knowledge_point }}</span>
              <span v-if="gradeResult?.mastery" class="mastery-tag">
                掌握度 {{ Math.round(gradeResult.mastery.mastery * 100) }}%
                （{{ gradeResult.mastery.correct_attempts }}/{{ gradeResult.mastery.total_attempts }} 题正确）
              </span>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app'
import { quizApi } from '../api/client'
import type { QuizResp, QuizStreamDone, QuizGradeResp } from '../api/client'
import { EditPen, MagicStick, CircleCheck, CircleClose, Collection, Menu } from '@element-plus/icons-vue'
import SubjectTree from '../components/SubjectTree.vue'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'

const router = useRouter()
const store = useAppStore()
const currentSubject = computed(() => store.currentSubject)
const currentChapter = computed(() => store.currentChapter)
const currentLesson = computed(() => store.currentLesson)

const difficulties = ['基础', '提高', '拓展'] as const
const questionTypes = ['选择', '填空', '简答'] as const

const difficulty = ref<'基础' | '提高' | '拓展'>('基础')
const questionType = ref<'选择' | '填空' | '简答'>('选择')
const generating = ref(false)
const quiz = ref<QuizResp | null>(null)
const selectedOption = ref<number | null>(null)
const userAnswer = ref('')
const revealed = ref(false)
const submitting = ref(false)
// 后端判分结果（无 quiz_id 时回退本地比对）
const gradeResult = ref<QuizGradeResp | null>(null)

function normalizeAnswer(ans: string): string {
  return ans.trim().replace(/[。．.！!？?]$/, '')
}

const isCorrect = computed(() => {
  if (!quiz.value) return false
  if (gradeResult.value) return gradeResult.value.is_correct
  // 本地兜底：仅在缺少 quiz_id（旧后端）时使用
  if (quiz.value.options && selectedOption.value !== null) {
    return quiz.value.correct_answer === String.fromCharCode(65 + selectedOption.value)
  }
  return normalizeAnswer(userAnswer.value) === normalizeAnswer(quiz.value.correct_answer)
})

function isCorrectOption(idx: number) {
  const answer = gradeResult.value?.correct_answer ?? quiz.value?.correct_answer
  if (!answer) return false
  return answer === String.fromCharCode(65 + idx)
}

async function generateQuiz() {
  if (!currentSubject.value) return
  generating.value = true
  revealed.value = false
  selectedOption.value = null
  userAnswer.value = ''
  gradeResult.value = null
  quiz.value = {
    question: '',
    options: null,
    correct_answer: '',
    explanation: '',
    knowledge_point: currentChapter.value?.name || '通用知识点',
    quiz_id: null,
  }

  let streamBuffer = ''
  try {
    await quizApi.generateStream(
      {
        subject: currentSubject.value.id,
        chapter: currentChapter.value?.id,
        lesson: currentLesson.value?.id,
        difficulty: difficulty.value,
        question_type: questionType.value,
      },
      (token: string) => {
        if (quiz.value) {
          streamBuffer += token
          const idx = streamBuffer.indexOf('【答案】')
          if (idx >= 0) {
            quiz.value.question = streamBuffer.slice(0, idx).trim()
          } else {
            quiz.value.question = streamBuffer
          }
        }
      },
      (result: QuizStreamDone) => {
        if (quiz.value) {
          quiz.value.question = result.question
          quiz.value.options = result.options
          quiz.value.correct_answer = result.correct_answer
          quiz.value.explanation = result.explanation
          quiz.value.knowledge_point = result.knowledge_point
          quiz.value.quiz_id = result.quiz_id
        }
      },
      (err: string) => {
        alert('出题失败：' + err)
        quiz.value = null
      },
    )
  } catch (e: any) {
    const msg = e?.message || '请稍后再试'
    alert('出题失败：' + msg)
    quiz.value = null
  } finally {
    generating.value = false
  }
}

async function revealAnswer() {
  if (!quiz.value) return

  // 无 quiz_id（旧后端或未落库）→ 保持原本地判分行为
  if (!quiz.value.quiz_id) {
    revealed.value = true
    return
  }

  const answer = quiz.value.options
    ? String.fromCharCode(65 + (selectedOption.value ?? 0))
    : userAnswer.value.trim()
  if (!answer) return

  submitting.value = true
  try {
    const { data } = await quizApi.submit(quiz.value.quiz_id, answer)
    gradeResult.value = data
    // 用后端权威结果覆盖（解析/答案可能与生成时略有出入）
    quiz.value.correct_answer = data.correct_answer
    quiz.value.explanation = data.explanation
    quiz.value.knowledge_point = data.knowledge_point
    revealed.value = true
  } catch (e: any) {
    const msg = e?.response?.data?.detail || '判分失败，请稍后再试'
    alert(msg)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.quiz-view {
  display: flex;
  height: calc(100vh - 60px);
}
.sidebar {
  width: 280px;
  background: var(--bg-card);
  border-right: 1px solid var(--border-light);
  overflow-y: auto;
  flex-shrink: 0;
}
.quiz-main {
  flex: 1;
  overflow-y: auto;
  background: var(--bg-base);
}
.quiz-container {
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-6);
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
  margin-right: var(--space-3);
}
.menu-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--border-medium);
}
.sidebar-overlay {
  display: none;
}

.quiz-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-8);
}
.quiz-header-main {
  flex: 1;
}
.quiz-header-main h1 {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 var(--space-3);
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: var(--space-3);
}
.quiz-desc {
  font-size: var(--text-md);
  color: var(--text-secondary);
  margin: 0;
}
.back-btn {
  margin-top: var(--space-1);
  flex-shrink: 0;
}

.quiz-config {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-light);
  padding: var(--space-6);
  margin-bottom: var(--space-6);
  box-shadow: var(--shadow-sm);
}
.config-row {
  display: flex;
  gap: var(--space-5);
  margin-bottom: var(--space-5);
}
.config-item {
  flex: 1;
}
.config-item label {
  display: block;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: var(--space-2);
}
.config-value {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-base);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
  border: 1px solid var(--border-light);
}
.config-value.chinese { border-left: 3px solid var(--subject-chinese); }
.config-value.math { border-left: 3px solid var(--subject-math); }
.config-value.english { border-left: 3px solid var(--subject-english); }
.config-value.science { border-left: 3px solid var(--subject-science); }
.config-value.social { border-left: 3px solid var(--subject-social); }

.config-options {
  display: flex;
  gap: var(--space-2);
}
.option-btn {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-light);
  background: var(--bg-base);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.option-btn:hover {
  border-color: var(--border-medium);
  color: var(--text-primary);
}
.option-btn.active {
  background: var(--accent-primary-light);
  border-color: var(--accent-primary);
  color: var(--accent-primary);
}

.generate-btn {
  width: 100%;
  margin-top: var(--space-2);
  border-radius: var(--radius-md) !important;
  font-size: var(--text-base);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
}

.quiz-card {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-light);
  padding: var(--space-6);
  box-shadow: var(--shadow-sm);
}
.quiz-tag {
  display: inline-block;
  padding: var(--space-1) var(--space-3);
  background: var(--accent-primary-light);
  color: var(--accent-primary);
  font-size: var(--text-xs);
  font-weight: 600;
  border-radius: 100px;
  margin-bottom: var(--space-4);
}
.quiz-question {
  font-size: var(--text-lg);
  line-height: 1.7;
  color: var(--text-primary);
  margin-bottom: var(--space-5);
}

.quiz-options {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-5);
}
.option-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  border: 2px solid var(--border-light);
  background: var(--bg-base);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.option-item:hover {
  border-color: var(--border-medium);
}
.option-item.selected {
  border-color: var(--accent-primary);
  background: var(--accent-primary-light);
}
.option-item.correct {
  border-color: var(--accent-success);
  background: var(--accent-success-light);
}
.option-item.wrong {
  border-color: var(--accent-danger);
  background: #fff0f0;
}
.option-label {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--bg-card);
  border: 1px solid var(--border-medium);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: 700;
  flex-shrink: 0;
}
.option-item.selected .option-label {
  background: var(--accent-primary);
  color: var(--text-inverse);
  border-color: var(--accent-primary);
}
.option-item.correct .option-label {
  background: var(--accent-success);
  color: var(--text-inverse);
  border-color: var(--accent-success);
}
.option-item.wrong .option-label {
  background: var(--accent-danger);
  color: var(--text-inverse);
  border-color: var(--accent-danger);
}
.option-text {
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.quiz-answer-input {
  margin-bottom: var(--space-5);
}

.quiz-actions {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.quiz-explanation {
  border-top: 1px solid var(--border-light);
  padding-top: var(--space-5);
}
.explanation-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  font-size: var(--text-lg);
  font-weight: 700;
}
.icon-correct { color: var(--accent-success); }
.icon-wrong { color: var(--accent-danger); }
.text-correct { color: var(--accent-success); }
.text-wrong { color: var(--accent-danger); }

.correct-answer {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-base);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
  font-size: var(--text-sm);
}
.explanation-body {
  font-size: var(--text-sm);
  line-height: 1.7;
  margin-bottom: var(--space-4);
}
.knowledge-point {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  flex-wrap: wrap;
}
.misconception-chip {
  padding: 2px var(--space-3);
  border-radius: 100px;
  background: #fff0f0;
  color: var(--accent-danger);
  font-size: var(--text-xs);
  font-weight: 600;
}
.diagnosis {
  padding: var(--space-3) var(--space-4);
  background: #fff8e6;
  border-left: 3px solid #e6a23c;
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--text-primary);
}
.mastery-tag {
  padding: 2px var(--space-2);
  border-radius: 100px;
  background: var(--accent-primary-light);
  color: var(--accent-primary);
  font-weight: 600;
}

@media (max-width: 768px) {
  .menu-btn {
    display: flex;
  }
  .sidebar {
    position: fixed;
    top: 60px;
    left: 0;
    bottom: 0;
    z-index: 100;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    box-shadow: var(--shadow-lg);
  }
  .sidebar.mobile-open {
    transform: translateX(0);
  }
  .sidebar-overlay {
    display: block;
    position: fixed;
    top: 60px;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.35);
    z-index: 99;
  }
  .quiz-container {
    padding: var(--space-4) var(--space-3);
  }
  .config-row {
    flex-direction: column;
    gap: var(--space-3);
  }
}
</style>
