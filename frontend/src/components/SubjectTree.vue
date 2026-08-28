<template>
  <div class="subject-tree">
    <div class="tree-header">
      <div class="tree-header-left">
        <el-icon size="16"><Collection /></el-icon>
        <span>课程目录</span>
      </div>
      <button class="collapse-btn" @click="store.toggleSidebarCollapse()">
        <el-icon size="14"><Fold /></el-icon>
      </button>
      <button class="close-sidebar-btn" @click="store.closeSidebar()">
        <el-icon size="16"><Close /></el-icon>
      </button>
    </div>

    <div v-if="!currentSubject" class="no-subject">
      <el-icon size="32" class="empty-icon"><FolderOpened /></el-icon>
      <p>请从首页选择课程</p>
      <button class="goto-btn" @click="$router.push('/')">去选课</button>
    </div>

    <div v-else class="tree-content">
      <div v-if="chapterList.length" class="chapter-list">
        <div
          v-for="ch in chapterList"
          :key="ch.id"
          class="chapter-block"
        >
          <div
            class="chapter-header"
            :class="{ expanded: isExpanded(ch.id), [currentSubject.id.split('_')[0]]: true }"
            @click="toggleExpand(ch)"
          >
            <el-icon size="12" class="expand-icon">
              <ArrowRight v-if="!isExpanded(ch.id)" />
              <ArrowDown v-else />
            </el-icon>
            <span class="chapter-name">{{ ch.name }}</span>
          </div>

          <div v-if="isExpanded(ch.id)" class="lesson-list">
            <div
              v-for="ls in lessonMap[ch.id] || []"
              :key="ls.id"
              class="lesson-item"
              :class="{ active: currentLesson?.id === ls.id }"
              @click.stop="onSelectLesson(ls)"
            >
              <span class="lesson-type">{{ ls.content_type }}</span>
              <span class="lesson-name">{{ ls.name }}</span>
            </div>
            <div v-if="loadingLessons[ch.id]" class="lesson-loading">
              <span>加载中...</span>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="loading-chapters">
        <div v-for="i in 6" :key="i" class="skeleton-row">
          <div class="skeleton-dot"></div>
          <div class="skeleton-line"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '../stores/app'
import { subjectApi } from '../api/client'
import type { Chapter, Lesson } from '../api/client'
import { Collection, FolderOpened, Document, ArrowRight, ArrowDown, Close, Fold } from '@element-plus/icons-vue'

const route = useRoute()
const store = useAppStore()

const currentSubject = computed(() => store.currentSubject)
const currentLesson = computed(() => store.currentLesson)
const chapterList = computed(() => {
  if (!currentSubject.value) return []
  return store.chapters[currentSubject.value.id] || []
})
const lessonMap = computed(() => store.lessons)

const expandedChapters = ref<Set<string>>(new Set())
const loadingLessons = ref<Record<string, boolean>>({})

function isExpanded(chapterId: string) {
  return expandedChapters.value.has(chapterId)
}

async function toggleExpand(ch: Chapter) {
  if (expandedChapters.value.has(ch.id)) {
    expandedChapters.value.delete(ch.id)
    return
  }
  expandedChapters.value.add(ch.id)

  if (!store.lessons[ch.id]) {
    loadingLessons.value[ch.id] = true
    try {
      const { data } = await subjectApi.lessons(currentSubject.value!.id, ch.id)
      store.setLessons(ch.id, data)
    } catch (e) {
      console.error('加载课程失败', e)
    } finally {
      loadingLessons.value[ch.id] = false
    }
  }
}

function onSelectLesson(ls: Lesson) {
  store.selectLesson(ls)
  store.closeSidebar()
  const ch = chapterList.value.find(c => c.id === ls.chapter_id)
  if (ch) store.selectChapter(ch)
}

async function loadChapters(subjectId: string) {
  if (store.chapters[subjectId]) return
  try {
    const { data } = await subjectApi.chapters(subjectId)
    store.setChapters(subjectId, data)
  } catch (e) {
    console.error('加载章节失败', e)
  }
}

watch(
  () => route.params.subject,
  async (val) => {
    const subjectId = val as string
    if (!subjectId) return
    // 深链接直达 /chat/:subject 时学科列表尚未加载（HomeView 未挂载），先按需拉取
    if (!store.subjectMap[subjectId]) {
      await store.ensureSubjects()
    }
    const s = store.subjectMap[subjectId]
    if (s) {
      store.selectSubject(s)
      loadChapters(subjectId)
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.subject-tree {
  padding: var(--space-4);
}
.tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-bottom: var(--space-4);
  padding: 0 var(--space-2);
}
.tree-header-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.collapse-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.close-sidebar-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.close-sidebar-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

@media (max-width: 768px) {
  .collapse-btn {
    display: none;
  }
  .close-sidebar-btn {
    display: flex;
  }
}

.no-subject {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--space-10) var(--space-4);
  color: var(--text-tertiary);
  text-align: center;
}
.empty-icon {
  margin-bottom: var(--space-3);
  opacity: 0.4;
}
.no-subject p {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
}
.goto-btn {
  padding: var(--space-2) var(--space-5);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-medium);
  background: var(--bg-card);
  color: var(--accent-primary);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.goto-btn:hover {
  background: var(--accent-primary-light);
  border-color: var(--accent-primary);
}

.subject-info {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-base);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
  border: 1px solid var(--border-light);
}
.subject-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: var(--subject-color);
  color: var(--text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  opacity: 0.9;
}
.subject-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.subject-name {
  font-weight: 600;
  font-size: var(--text-base);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.subject-pub {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.chapter-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.chapter-block {
  border-radius: var(--radius-md);
  overflow: hidden;
}
.chapter-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  user-select: none;
}
.chapter-header:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.chapter-header.expanded {
  font-weight: 600;
  color: var(--text-primary);
}
.expand-icon {
  color: var(--text-tertiary);
  transition: transform var(--transition-fast);
  flex-shrink: 0;
}
.chapter-header.expanded .expand-icon {
  color: var(--accent-primary);
}
.chapter-name {
  line-height: 1.4;
}

.lesson-list {
  padding-left: var(--space-6);
  padding-bottom: var(--space-1);
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.lesson-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.lesson-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.lesson-item.active {
  background: var(--accent-primary-light);
  color: var(--accent-primary);
  font-weight: 500;
}
.lesson-type {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--border-light);
  color: var(--text-tertiary);
  flex-shrink: 0;
  line-height: 1.4;
}
.lesson-item.active .lesson-type {
  background: rgba(44, 90, 160, 0.15);
  color: var(--accent-primary);
}
.lesson-name {
  line-height: 1.4;
}
.lesson-loading {
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.loading-chapters {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
}
.skeleton-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.skeleton-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--border-light);
  flex-shrink: 0;
  animation: pulse 1.5s infinite;
}
.skeleton-line {
  height: 14px;
  border-radius: 3px;
  background: var(--border-light);
  flex: 1;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.subject-info.chinese { --subject-color: var(--subject-chinese); }
.subject-info.math { --subject-color: var(--subject-math); }
.subject-info.english { --subject-color: var(--subject-english); }
.subject-info.science { --subject-color: var(--subject-science); }
.subject-info.social { --subject-color: var(--subject-social); }
</style>
