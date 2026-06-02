<template>
  <div class="task-center">
    <el-badge :value="runningCount" :hidden="runningCount === 0" class="task-badge">
      <button class="nav-btn" @click="drawerVisible = true" title="任务中心">
        <el-icon size="16"><Bell /></el-icon>
      </button>
    </el-badge>

    <el-drawer v-model="drawerVisible" :size="drawerSize" :with-header="true">
      <template #header>
        <div class="drawer-header">
          <span>后台任务</span>
          <div class="header-actions">
            <el-button :icon="Refresh" @click="loadTasks" :loading="loading" title="刷新" link></el-button>
            <el-button :icon="isMaximized ? CopyDocument : FullScreen" @click="toggleMaximize" :title="isMaximized ? '还原' : '最大化'" link></el-button>
          </div>
        </div>
      </template>
      <div class="task-content">
        <div class="task-list-wrapper">
          <div class="task-list-header">
            <span class="col-filename">文件名</span>
            <span class="col-type">类型</span>
            <span class="col-status">状态</span>
            <span class="col-time">时间</span>
            <span class="col-progress">进度</span>
          </div>
          <div class="task-list-container">
            <el-empty v-if="paginatedTasks.length === 0" description="暂无后台任务" />
            <div
              v-for="task in paginatedTasks"
              :key="task.task_id"
              class="task-item"
              :class="`status-${task.status}`"
              :title="task.message || undefined"
            >
              <span class="col-filename">{{ task.filename }}</span>
              <span class="col-type">{{ typeLabel(task.type) }}</span>
              <span class="col-status">
                <el-tag :type="statusType(task.status)" size="small">
                  {{ statusLabel(task.status) }}
                </el-tag>
              </span>
              <span class="col-time">{{ formatTime(task.created_at) }}</span>
              <span class="col-progress">
                <el-progress
                  :percentage="task.progress"
                  :status="task.status === 'failed' ? 'exception' : task.status === 'completed' ? 'success' : ''"
                  :stroke-width="12"
                  text-inside
                />
              </span>
            </div>
          </div>
        </div>
        <div class="pagination-area">
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[5, 10, 20, 50]"
            :total="total"
            layout="total, sizes, prev, pager, next"
            @size-change="handleSizeChange"
          />
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { Bell, Refresh, FullScreen, CopyDocument } from '@element-plus/icons-vue'
import { adminApi, type TaskInfo } from '../api/client'

const drawerVisible = ref(false)
const tasks = ref<TaskInfo[]>([])
const loading = ref(false)
const isMaximized = ref(false)
const drawerSize = computed(() => isMaximized.value ? '100%' : '720px')

const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
const paginatedTasks = computed(() => tasks.value)

function handleSizeChange() {
  currentPage.value = 1
  loadTasks()
}

function toggleMaximize() {
  isMaximized.value = !isMaximized.value
}

const runningCount = computed(() =>
  tasks.value.filter((t) => t.status === 'pending' || t.status === 'running').length,
)

const typeMap: Record<string, string> = {
  'generate-outline': '生成大纲',
  'generate': '生成教材',
  'ingest': '向量化',
  'batch-ingest': '批量更新',
}

const statusMap: Record<string, string> = {
  'pending': '等待中',
  'running': '执行中',
  'completed': '已完成',
  'failed': '失败',
  'error': '错误',
  'partial': '部分完成',
  'skipped': '已跳过',
}

const statusTypeMap: Record<string, '' | 'success' | 'warning' | 'danger'> = {
  'pending': '',
  'running': 'warning',
  'completed': 'success',
  'failed': 'danger',
  'error': 'danger',
  'partial': 'warning',
  'skipped': '',
}

function typeLabel(type: string) {
  return typeMap[type] || type
}

function statusLabel(status: string) {
  return statusMap[status] || status
}

function statusType(status: string) {
  return statusTypeMap[status] || ''
}

function formatTime(ts: string) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

async function loadTasks() {
  loading.value = true
  try {
    const { data } = await adminApi.listTasks({
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value,
    })
    tasks.value = data.tasks || []
    total.value = data.total || 0
  } catch {
    // 静默失败，不打扰用户
  } finally {
    loading.value = false
  }
}

function onTaskSubmitted() {
  loadTasks()
}

onMounted(() => {
  loadTasks()
  window.addEventListener('refresh-tasks', onTaskSubmitted)
})

onUnmounted(() => {
  window.removeEventListener('refresh-tasks', onTaskSubmitted)
})

watch(drawerVisible, (visible) => {
  if (visible) loadTasks()
})

watch(currentPage, () => {
  loadTasks()
})
</script>

<style scoped>
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

:deep(.el-drawer__header) {
  margin-bottom: 0;
}

:deep(.el-drawer__body) {
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}

.task-center {
  display: flex;
  align-items: center;
}
.task-center .nav-btn {
  padding: var(--space-2);
  min-width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.task-center .nav-btn:hover {
  background: var(--bg-hover);
  color: var(--text-secondary);
}
.task-badge :deep(.el-badge__content) {
  top: 4px;
  right: 4px;
}

.task-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 12px 16px;
  box-sizing: border-box;
}

.task-list-wrapper {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.task-list-header {
  display: grid;
  grid-template-columns: 1fr 55px 55px 95px 90px;
  gap: 8px;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--el-fill-color-light);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}

.task-list-container {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.task-item {
  display: grid;
  grid-template-columns: 1fr 55px 55px 95px 90px;
  gap: 8px;
  padding: 10px 12px;
  align-items: center;
  border-bottom: 1px solid var(--border-light);
  font-size: 12px;
  transition: background 0.15s;
}

.task-item:hover {
  background: var(--el-fill-color-light);
}

.task-item.status-running {
  border-left: 3px solid var(--el-color-primary);
  padding-left: 9px;
}
.task-item.status-completed {
  border-left: 3px solid var(--el-color-success);
  padding-left: 9px;
}
.task-item.status-failed,
.task-item.status-error {
  border-left: 3px solid var(--el-color-danger);
  padding-left: 9px;
}
.task-item.status-pending {
  border-left: 3px solid var(--el-color-warning);
  padding-left: 9px;
}

.col-type {
  font-weight: 500;
  color: var(--text-primary);
}

.col-filename {
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.col-status {
  justify-self: center;
}

.col-time {
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.col-progress :deep(.el-progress-bar__outer) {
  border-radius: 6px;
}
.col-progress :deep(.el-progress-bar__inner) {
  border-radius: 6px;
}

.pagination-area {
  flex-shrink: 0;
  padding-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
