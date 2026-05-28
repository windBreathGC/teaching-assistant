import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Subject, Chapter, Lesson } from '../api/client'

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
    subjectMap,
    setSubjects,
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
