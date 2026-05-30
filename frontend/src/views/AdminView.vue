<template>
  <div class="admin-page">
    <div class="admin-header">
      <div class="header-left">
        <h1>教材管理</h1>
        <p class="subtitle">扫描、解析、向量化教材文件</p>
      </div>
      <div>
        <el-button
          type="primary"
          :loading="hasBatchTask"
          :disabled="hasBatchTask"
          @click="handleBatchIngest"
        >
          一键全量更新
        </el-button>
        <el-button :icon="Refresh" @click="loadData" :loading="loading">
          刷新
        </el-button>
      </div>
    </div>

    <div class="admin-content" ref="contentRef">

      <div class="table-area" ref="tableAreaRef">
        <el-table
          :data="paginatedTextbooks"
          v-loading="loading"
          stripe
          :height="tableHeight"
          style="width: 100%"
        >
          <el-table-column prop="filename" label="文件名" min-width="280" show-overflow-tooltip/>
          <el-table-column prop="subject" label="学科" width="80" />
          <el-table-column prop="grade" label="年级" width="100" />
          <el-table-column prop="semester" label="学期" width="80" />
          <el-table-column label="解析状态" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.parsed" type="success" size="small">已解析</el-tag>
              <el-tag v-else type="info" size="small">未解析</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="向量化" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.ingested && !row.outdated" type="success" size="small">
                已入库 {{ row.chunks ? `(${row.chunks})` : '' }}
              </el-tag>
              <el-tag v-else-if="row.outdated" type="warning" size="small">需更新</el-tag>
              <el-tag v-else type="info" size="small">未入库</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button
                size="small"
                :type="row.parsed ? 'default' : 'primary'"
                :loading="parsing[row.filename]"
                @click="handleParse(row.filename)"
              >
                解析
              </el-button>
              <el-button
                size="small"
                :type="row.ingested && !row.outdated ? 'default' : 'success'"
                :loading="ingesting[row.filename]"
                :disabled="!row.parsed"
                @click="handleIngest(row.filename)"
              >
                向量化
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pagination-area">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[5, 10, 20, 25]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          @size-change="handleSizeChange"
        />
      </div>

      <!-- 任务进度面板 -->
      <div v-if="activeTasks.length > 0" class="task-panel">
        <h3>进行中的任务</h3>
        <div v-for="task in activeTasks" :key="task.task_id" class="task-item">
          <div class="task-info">
            <span class="task-name">{{ task.filename }}</span>
            <span class="task-status">{{ task.message }}</span>
          </div>
          <el-progress
            :percentage="task.progress"
            :status="task.progress === 100 ? 'success' : ''"
            :stroke-width="16"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { adminApi, type TextbookItem, type TaskInfo } from '../api/client'

const textbooks = ref<TextbookItem[]>([])
const loading = ref(false)
const parsing = ref<Record<string, boolean>>({})
const ingesting = ref<Record<string, boolean>>({})
const tasks = ref<Record<string, TaskInfo>>({})
const pollTimers = ref<Record<string, number>>({})

// 分页
const currentPage = ref(1)
const pageSize = ref(10)
const total = computed(() => textbooks.value.length)
const paginatedTextbooks = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return textbooks.value.slice(start, start + pageSize.value)
})

function handleSizeChange() {
  currentPage.value = 1
}

// 自适应高度
const contentRef = ref<HTMLDivElement>()
const tableAreaRef = ref<HTMLDivElement>()
const tableHeight = ref(400)

function updateTableHeight() {
  if (tableAreaRef.value) {
    tableHeight.value = tableAreaRef.value.clientHeight
  }
}

let resizeObserver: ResizeObserver | null = null

const activeTasks = computed(() =>
  Object.values(tasks.value).filter(
    (t) => t.status === 'pending' || t.status === 'running',
  ),
)

const hasBatchTask = computed(() =>
  activeTasks.value.some((t) => t.type === 'batch-ingest'),
)

async function loadData() {
  loading.value = true
  try {
    const { data } = await adminApi.listTextbooks()
    textbooks.value = data
  } catch (e) {
    ElMessage.error('加载教材列表失败')
  } finally {
    loading.value = false
  }
}

async function handleParse(filename: string) {
  parsing.value[filename] = true
  try {
    await adminApi.parse(filename)
    ElMessage.success(`解析完成: ${filename}`)
    await loadData()
  } catch (e: any) {
    ElMessage.error(`解析失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    parsing.value[filename] = false
  }
}

async function handleIngest(filename: string) {
  ingesting.value[filename] = true
  try {
    const { data } = await adminApi.ingest(filename)
    const taskId = data.task_id
    ElMessage.info(`向量化任务已提交: ${taskId}`)

    tasks.value[taskId] = {
      task_id: taskId,
      type: 'ingest',
      filename,
      status: 'pending',
      progress: 0,
      message: '等待执行',
      result: null,
    }

    // 开始轮询进度
    startPolling(taskId)
  } catch (e: any) {
    ElMessage.error(`提交失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    ingesting.value[filename] = false
  }
}

async function handleBatchIngest() {
  try {
    await ElMessageBox.confirm(
      '将扫描 textbook/ 目录下所有教材文件，自动解析并执行向量化入库。未变更的文件会自动跳过。是否继续？',
      '一键全量更新',
      {
        confirmButtonText: '确认更新',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  try {
    const { data } = await adminApi.batchIngest()
    const taskId = data.task_id
    ElMessage.info(`批量更新任务已提交: ${taskId}`)

    tasks.value[taskId] = {
      task_id: taskId,
      type: 'batch-ingest',
      filename: '批量更新',
      status: 'pending',
      progress: 0,
      message: '等待执行',
      result: null,
    }

    startPolling(taskId)
  } catch (e: any) {
    ElMessage.error(`提交失败: ${e.response?.data?.detail || e.message}`)
  }
}

function startPolling(taskId: string) {
  if (pollTimers.value[taskId]) {
    clearInterval(pollTimers.value[taskId])
  }

  const timer = window.setInterval(async () => {
    try {
      const { data } = await adminApi.getTask(taskId)
      tasks.value[taskId] = data

      if (data.status === 'completed' || data.status === 'failed' || data.status === 'error' || data.status === 'partial') {
        clearInterval(timer)
        delete pollTimers.value[taskId]

        if (data.status === 'completed') {
          ElMessage.success(`完成: ${data.filename}`)
        } else if (data.status === 'partial') {
          ElMessage.warning(`部分完成: ${data.message}`)
        } else {
          ElMessage.error(`失败: ${data.message}`)
        }
        await loadData()
      }
    } catch (e) {
      clearInterval(timer)
      delete pollTimers.value[taskId]
      ElMessage.error('查询任务状态失败，请刷新页面重试')
    }
  }, 2000)

  pollTimers.value[taskId] = timer
}

onMounted(() => {
  loadData()
  updateTableHeight()
  resizeObserver = new ResizeObserver(() => updateTableHeight())
  if (tableAreaRef.value) {
    resizeObserver.observe(tableAreaRef.value)
  }
})

onUnmounted(() => {
  Object.values(pollTimers.value).forEach((timer) => clearInterval(timer))
  resizeObserver?.disconnect()
})
</script>

<style scoped>
.admin-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 24px;
  box-sizing: border-box;
  overflow: hidden;
  max-width: 1200px;
  margin: 0 auto;
}
.admin-header {
  flex-shrink: 0;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.header-left h1 {
  margin: 0;
  font-size: 24px;
  color: var(--text-primary);
}
.subtitle {
  margin: 4px 0 0;
  color: var(--text-tertiary);
  font-size: 14px;
}
.header-actions {
  display: flex;
  gap: 12px;
  flex-shrink: 0;
}
.admin-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.table-area {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.pagination-area {
  flex-shrink: 0;
  padding-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.task-panel {
  flex-shrink: 0;
  margin-top: 12px;
  padding: 12px 16px;
  background: var(--bg-card);
  border-radius: 8px;
  border: 1px solid var(--border-light);
}
.task-panel h3 {
  margin: 0 0 12px;
  font-size: 16px;
  color: var(--text-primary);
}
.task-item {
  margin-bottom: 12px;
}
.task-item:last-child {
  margin-bottom: 0;
}
.task-info {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 14px;
}
.task-name {
  font-weight: 500;
  color: var(--text-primary);
}
.task-status {
  color: var(--text-secondary);
}
</style>
