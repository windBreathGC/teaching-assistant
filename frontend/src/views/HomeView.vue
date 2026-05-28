<template>
  <div class="home-view">
    <section class="hero-section">
      <h1 class="hero-title">AI 伴学，循序渐进</h1>
      <p class="hero-subtitle">
        {{ selectedGrade ? '选择一门课程，与智能助教一起探索知识的奥秘' : '选择学期，开始你的学习之旅' }}
      </p>
    </section>

    <!-- 年级列表 -->
    <section v-if="!selectedGrade" class="grades-section">
      <div v-if="loading" class="state-message">
        <el-icon class="spin" size="24"><Loading /></el-icon>
        <p>正在加载课程...</p>
      </div>

      <div v-else-if="error" class="state-message error">
        <el-icon size="32"><Warning /></el-icon>
        <p>{{ error }}</p>
        <el-button type="primary" @click="loadSubjects">重试</el-button>
      </div>

      <div v-else-if="Object.keys(gradeGroups).length === 0" class="state-message">
        <el-icon size="32"><Document /></el-icon>
        <p>暂无课程数据</p>
      </div>

      <div v-else class="grades-grid">
        <div
          v-for="(list, grade) in gradeGroups"
          :key="grade"
          class="grade-card"
          @click="enterGrade(grade)"
        >
          <div class="grade-badge">{{ gradeShortName(grade) }}</div>
          <div class="grade-content">
            <h3 class="grade-name">{{ grade }}</h3>
            <p class="grade-meta">{{ list.length }} 门学科</p>
            <p class="grade-desc">{{ gradeVersions(list) }}</p>
            <div class="grade-action">
              <span>进入学习</span>
              <el-icon size="14"><ArrowRight /></el-icon>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 学科列表 -->
    <section v-else class="subjects-section">
      <div class="back-bar">
        <button class="back-btn" @click="selectedGrade = ''">
          <el-icon size="14"><ArrowLeft /></el-icon>
          <span>返回学期选择</span>
        </button>
        <span class="grade-label">{{ selectedGrade }}</span>
      </div>

      <div class="subjects-grid">
        <div
          v-for="s in gradeSubjects"
          :key="s.id"
          class="subject-card"
          :class="s.id.split('_')[0]"
          @click="goChat(s)"
        >
          <div class="card-accent"></div>
          <div class="card-content">
            <div class="card-icon">
              <el-icon size="32"><Document /></el-icon>
            </div>
            <h3 class="card-name">{{ s.name }}</h3>
            <p class="card-meta">{{ s.publisher }} · {{ s.version }}</p>
            <p class="card-desc">{{ s.description }}</p>
            <div class="card-action">
              <span>开始学习</span>
              <el-icon size="14"><ArrowRight /></el-icon>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useAppStore } from '../stores/app'
import { subjectApi } from '../api/client'
import type { Subject } from '../api/client'
import { Document, ArrowRight, ArrowLeft, Loading, Warning } from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()
const store = useAppStore()
const { subjects } = storeToRefs(store)
const loading = ref(false)
const error = ref('')
const selectedGrade = ref('')

const gradeGroups = computed(() => {
  const map: Record<string, Subject[]> = {}
  subjects.value.forEach((s) => {
    const g = s.grade || '未分类'
    if (!map[g]) map[g] = []
    map[g].push(s)
  })
  return map
})

const gradeSubjects = computed(() => {
  if (!selectedGrade.value) return []
  return gradeGroups.value[selectedGrade.value] || []
})

async function loadSubjects() {
  if (subjects.value.length > 0) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await subjectApi.list()
    store.setSubjects(data)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    if (msg.includes('Network Error') || msg.includes('ECONNREFUSED')) {
      error.value = '无法连接到后端服务，请确认后端已启动 (python start.py)'
    } else {
      error.value = '加载课程失败: ' + msg
    }
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadSubjects()
  const gradeFromQuery = route.query.grade as string
  if (gradeFromQuery && gradeGroups.value[gradeFromQuery]) {
    selectedGrade.value = gradeFromQuery
  }
})

function enterGrade(grade: string) {
  selectedGrade.value = grade
}

function goChat(s: { id: string; name: string }) {
  router.push({ name: 'chat', params: { subject: s.id } })
}

function gradeShortName(grade: string): string {
  const map: Record<string, string> = {
    '七年级上册': '七上',
    '七年级下册': '七下',
    '八年级上册': '八上',
    '八年级下册': '八下',
    '九年级上册': '九上',
    '九年级下册': '九下',
  }
  return map[grade] || grade.slice(0, 2)
}

function gradeVersions(list: Subject[]): string {
  const versions = [...new Set(list.map((s) => s.publisher))]
  return versions.join(' / ')
}
</script>

<style scoped>
.home-view {
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--space-3) var(--space-6);
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.hero-section {
  text-align: center;
  margin-bottom: var(--space-2);
  flex-shrink: 0;
}
.hero-title {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 var(--space-2);
  letter-spacing: 1px;
}
.hero-subtitle {
  font-size: var(--text-base);
  color: var(--text-secondary);
  margin: 0;
  max-width: 480px;
  margin-left: auto;
  margin-right: auto;
  line-height: 1.5;
}

.grades-section,
.subjects-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* 年级卡片 */
.grades-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-2);
  flex: 1;
  align-content: start;
}
.grade-card {
  position: relative;
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-light);
  cursor: pointer;
  overflow: hidden;
  transition: all var(--transition-base);
  box-shadow: var(--shadow-sm);
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
}
.grade-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
}
.grade-badge {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary, var(--accent-primary)) 100%);
  color: var(--text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-base);
  font-weight: 700;
  flex-shrink: 0;
  letter-spacing: 1px;
}
.grade-content {
  flex: 1;
  min-width: 0;
}
.grade-name {
  font-family: var(--font-display);
  font-size: var(--text-base);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 2px;
}
.grade-meta {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 0 0 var(--space-1);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.grade-desc {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.4;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.grade-action {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--accent-primary);
  transition: gap var(--transition-fast);
}
.grade-card:hover .grade-action {
  gap: var(--space-3);
}

/* 返回栏 */
.back-bar {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
  flex-shrink: 0;
}
.back-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-light);
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.back-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--border-medium);
}
.grade-label {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-tertiary);
}

/* 学科卡片 */
.subjects-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-3);
  flex: 1;
  align-content: start;
}
.subject-card {
  position: relative;
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-light);
  cursor: pointer;
  overflow: hidden;
  transition: all var(--transition-base);
  box-shadow: var(--shadow-sm);
}
.subject-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
}
.card-accent {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: var(--subject-color);
  opacity: 0;
  transition: opacity var(--transition-base);
}
.subject-card:hover .card-accent {
  opacity: 1;
}
.card-content {
  padding: var(--space-4);
}
.card-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--subject-color);
  color: var(--text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-2);
  opacity: 0.9;
}
.card-name {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 var(--space-1);
}
.card-meta {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin: 0 0 var(--space-2);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.card-desc {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0 0 var(--space-2);
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-action {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--accent-primary);
  transition: gap var(--transition-fast);
}
.subject-card:hover .card-action {
  gap: var(--space-2);
}

.subject-card.chinese { --subject-color: var(--subject-chinese); }
.subject-card.math { --subject-color: var(--subject-math); }
.subject-card.english { --subject-color: var(--subject-english); }
.subject-card.science { --subject-color: var(--subject-science); }
.subject-card.social { --subject-color: var(--subject-social); }

.state-message {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-16) var(--space-6);
  color: var(--text-secondary);
  text-align: center;
}
.state-message p {
  margin: 0;
  font-size: var(--text-md);
}
.state-message.error {
  color: var(--accent-danger);
}

/* 响应式 */
@media (max-width: 960px) {
  .grades-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .subjects-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}
@media (max-width: 640px) {
  .grades-grid {
    grid-template-columns: 1fr;
  }
  .subjects-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.spin {
  animation: spin 1s linear infinite;
}
</style>
