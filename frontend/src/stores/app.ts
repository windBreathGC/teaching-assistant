import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Subject, Chapter, Lesson } from '../api/client'
import { subjectApi } from '../api/client'

export const useAppStore = defineStore('app', () => {
  const subjects = ref<Subject[]>([])
  const chapters = ref<Record<string, Chapter[]>>({})
  const lessons = ref<Record<string, Lesson[]>>({})
  const currentSubject = ref<Subject | null>(null)
  const currentChapter = ref<Chapter | null>(null)
  const currentLesson = ref<Lesson | null>(null)
  const loading = ref(false)
  const sidebarVisible = ref(false)
  const sidebarCollapsed = ref(false)
  const isMobile = ref(false)

  function updateIsMobile() {
    isMobile.value = window.matchMedia('(max-width: 768px)').matches
  }

  updateIsMobile()

  if (typeof window !== 'undefined') {
    const mql = window.matchMedia('(max-width: 768px)')
    mql.addEventListener('change', (e) => {
      isMobile.value = e.matches
      if (!e.matches) {
        sidebarVisible.value = false
      }
    })
  }

  function toggleSidebar() {
    sidebarVisible.value = !sidebarVisible.value
    if (sidebarVisible.value) {
      sidebarCollapsed.value = false
    }
  }

  function closeSidebar() {
    sidebarVisible.value = false
  }

  function toggleSidebarCollapse() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  const subjectMap = computed(() => {
    const map: Record<string, Subject> = {}
    subjects.value.forEach(s => { map[s.id] = s })
    return map
  })

  function setSubjects(list: Subject[]) {
    subjects.value = list
  }

  // 学科列表按需加载（深链接直达 /chat/:subject 时 HomeView 不会挂载，
  // 需要由使用方自行确保数据就绪）。并发调用共享同一个 Promise，避免重复请求。
  let subjectsPromise: Promise<void> | null = null

  function ensureSubjects(): Promise<void> {
    if (subjects.value.length) return Promise.resolve()
    if (!subjectsPromise) {
      subjectsPromise = subjectApi
        .list()
        .then(({ data }) => {
          subjects.value = data
        })
        .catch((e) => {
          console.error('加载学科列表失败', e)
        })
        .finally(() => {
          subjectsPromise = null
        })
    }
    return subjectsPromise
  }

  function setChapters(subjectId: string, list: Chapter[]) {
    chapters.value[subjectId] = list
  }

  function setLessons(chapterId: string, list: Lesson[]) {
    lessons.value[chapterId] = list
  }

  function selectSubject(subject: Subject | null) {
    currentSubject.value = subject
    currentChapter.value = null
    currentLesson.value = null
  }

  function selectChapter(chapter: Chapter | null) {
    currentChapter.value = chapter
    if (currentLesson.value && currentLesson.value.chapter_id !== chapter?.id) {
      currentLesson.value = null
    }
  }

  function selectLesson(lesson: Lesson | null) {
    currentLesson.value = lesson
  }

  return {
    subjects,
    chapters,
    lessons,
    currentSubject,
    currentChapter,
    currentLesson,
    loading,
    sidebarVisible,
    sidebarCollapsed,
    isMobile,
    subjectMap,
    setSubjects,
    ensureSubjects,
    setChapters,
    setLessons,
    selectSubject,
    selectChapter,
    selectLesson,
    toggleSidebar,
    closeSidebar,
    toggleSidebarCollapse,
  }
})
