<template>
  <div class="admin-page">
    <div class="admin-header">
      <div class="header-left">
        <span style="font-size: 20px; font-weight: 700;">教材管理</span><span class="subtitle">扫描、解析、向量化教材文件</span>
      </div>
      <div v-if="activeTab === 'list'">
        <el-button
          type="primary"
          @click="handleBatchIngest"
        >
          一键全量更新
        </el-button>
        <el-button :icon="Refresh" @click="loadData" :loading="loading">
          刷新
        </el-button>
      </div>
    </div>

    <div class="tab-bar">
      <button
        :class="['tab-btn', { active: activeTab === 'list' }]"
        @click="activeTab = 'list'"
      >
        教材列表
      </button>
      <button
        :class="['tab-btn', { active: activeTab === 'generate' }]"
        @click="activeTab = 'generate'"
      >
        智能采集
      </button>
      <button
        :class="['tab-btn', { active: activeTab === 'textbook' }]"
        @click="activeTab = 'textbook'"
      >
        教材生成
      </button>
    </div>

    <div class="tab-content-area">
      <Transition name="tab-fade" mode="out-in">
        <div v-if="activeTab === 'list'" key="list" class="admin-content">

      <div class="table-area" ref="tableAreaRef">
        <el-table
          :data="paginatedTextbooks"
          v-loading="loading"
          stripe
          :height="tableHeight"
          style="width: 100%"
        >
          <el-table-column prop="filename" label="文件名" min-width="280" show-overflow-tooltip/>
          <el-table-column label="学科" width="90" align="center">
            <template #default="{ row }">
              <span class="subject-pill" :class="subjectClass(row.subject)">{{ row.subject }}</span>
            </template>
          </el-table-column>
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
          <el-table-column label="操作" width="100" fixed="right" align="center">
            <template #default="{ row }">
              <div class="action-btns">
                <el-button
                  size="small"
                  circle
                  :type="row.parsed ? 'default' : 'primary'"
                  :loading="parsing[row.filename]"
                  @click="handleParse(row.filename)"
                  title="解析"
                >
                  <el-icon><Document /></el-icon>
                </el-button>
                <el-button
                  size="small"
                  circle
                  :type="row.ingested && !row.outdated ? 'default' : 'success'"
                  :loading="ingesting[row.filename]"
                  :disabled="!row.parsed"
                  @click="handleIngest(row.filename)"
                  title="向量化"
                >
                  <el-icon><Lightning /></el-icon>
                </el-button>
              </div>
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

    </div>

    <!-- 智能采集面板 -->
        <div v-else-if="activeTab === 'generate'" key="generate" class="generate-panel">
      <!-- 教材基本信息 -->
      <div id="gen-step-1" class="form-card">
        <h4 class="form-card-title">教材基本信息</h4>
        <el-form :model="generateForm" label-width="90px" class="gen-form">
          <el-form-item label="学科">
            <el-select v-model="generateForm.subject" placeholder="选择学科" style="width: 100%">
              <el-option label="语文" value="语文" />
              <el-option label="数学" value="数学" />
              <el-option label="英语" value="英语" />
              <el-option label="科学" value="科学" />
              <el-option label="社会" value="社会" />
            </el-select>
          </el-form-item>
          <el-form-item label="年级">
            <el-select v-model="generateForm.grade" placeholder="选择年级" style="width: 100%">
              <el-option label="七年级" value="七年级" />
              <el-option label="八年级" value="八年级" />
              <el-option label="九年级" value="九年级" />
            </el-select>
          </el-form-item>
          <el-form-item label="学期">
            <el-select v-model="generateForm.semester" placeholder="选择学期" style="width: 100%">
              <el-option label="上册" value="上册" />
              <el-option label="下册" value="下册" />
            </el-select>
          </el-form-item>
          <el-form-item label="出版社">
            <el-input v-model="generateForm.publisher" placeholder="如：部编版、浙教版" />
          </el-form-item>
          <el-form-item label="版本年份">
            <el-input v-model="generateForm.version_year" placeholder="如：2024" />
          </el-form-item>
          <el-form-item label="适用地区">
            <el-input v-model="generateForm.region" placeholder="如：浙江省杭州市" />
          </el-form-item>
          <el-form-item label="特别说明">
            <el-input
              v-model="generateForm.notes"
              type="textarea"
              :rows="2"
              placeholder="可选：补充说明，如使用特定课程标准、侧重某些知识点等"
            />
          </el-form-item>
        </el-form>
      </div>

      <!-- 步骤2：大模型配置 -->
      <div id="gen-step-2" class="form-card">
        <h4 class="form-card-title">大模型配置</h4>
        <el-alert
          v-if="modelStore.models.length === 0"
          type="info"
          :closable="false"
          title="提示"
          description="暂无模型配置，请先在右上角【模型接入】中添加模型提供商"
          show-icon
          style="margin-bottom: 12px"
        />
        <el-form label-width="90px" class="gen-form">
          <el-form-item label="选择模型">
            <el-select v-model="selectedModelId" placeholder="选择已配置的模型" style="width: 100%">
              <el-option
                v-for="opt in modelStore.modelOptions"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
          </el-form-item>
          <div v-if="selectedModel" class="model-preview">
            <div class="preview-item">API地址: {{ selectedModel.base_url }}</div>
            <div class="preview-item">模型: {{ selectedModel.model_name }}</div>
            <div class="preview-item">温度: {{ selectedModel.temperature }}</div>
          </div>
        </el-form>
      </div>

      <!-- 步骤3：生成 -->
      <div id="gen-step-3" class="gen-actions">
        <el-button
          type="primary"
          size="large"
          :loading="generatingOutline"
          @click="handleGenerateOutline"
          class="generate-main-btn"
        >
          <el-icon size="18"><MagicStick /></el-icon>
          生成教材大纲
        </el-button>
      </div>
    </div>

    <!-- 教材生成面板 -->
        <div v-else-if="activeTab === 'textbook'" key="textbook" class="generate-panel textbook-panel">
      <div class="textbook-layout">
        <!-- 左侧：控制面板 -->
        <div class="textbook-sidebar">
          <el-alert
            v-if="modelStore.models.length === 0"
            type="info"
            :closable="false"
            title="提示"
            description="暂无模型配置，请先在右上角【模型接入】中添加模型提供商"
            show-icon
            style="margin-bottom: 12px"
          />

          <div class="form-card">
            <h4 class="form-card-title">模型配置</h4>
            <el-form label-width="90px" class="gen-form">
              <el-select v-model="selectedModelId" placeholder="选择已配置的模型" style="width: 100%">
                <el-option
                  v-for="opt in modelStore.modelOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
              <div v-if="selectedModel" class="model-preview">
                <div class="preview-item">API地址: {{ selectedModel.base_url }}</div>
                <div class="preview-item">模型: {{ selectedModel.model_name }}</div>
                <div class="preview-item">温度: {{ selectedModel.temperature }}</div>
              </div>
            </el-form>
          </div>

          <div class="form-card">
            <h4 class="form-card-title">选择大纲</h4>
            <div v-if="outlineOptions.length > 0" class="outline-selector">
              <el-select
                v-model="selectedOutlineTaskId"
                placeholder="选择已生成的大纲"
                style="width: 100%"
                clearable
              >
                <el-option
                  v-for="opt in outlineOptions"
                  :key="opt.task_id"
                  :label="opt.label"
                  :value="opt.task_id"
                />
              </el-select>
            </div>
            <el-alert
              v-else
              type="info"
              :closable="false"
              title="暂无大纲"
              description="请先在【智能采集】页签中生成教材大纲"
              show-icon
              style="margin: 12px 0"
            />
          </div>

          <div class="gen-actions">
            <el-button
              :disabled="!canGenerate"
              type="success"
              size="large"
              :loading="hasGenerateTask"
              @click="handleGenerateTextbook"
              class="generate-main-btn"
            >
              确认生成教材
            </el-button>
          </div>

          <div v-if="generateTask" class="task-panel">
            <div class="task-item">
              <div class="task-info">
                <span class="task-name">{{ generateTask.filename }}</span>
                <span class="task-status">{{ generateTask.message }}</span>
              </div>
              <el-progress
                :percentage="generateTask.progress"
                :status="generateTask.progress === 100 ? 'success' : ''"
                :stroke-width="16"
              />
            </div>
          </div>

          <div v-if="generatedFile" class="gen-actions">
            <el-button type="warning" :loading="analyzing" @click="handleAnalyze">
              分析教材
            </el-button>
            <el-button
              v-if="analysisReport?.ready_for_ingest"
              type="success"
              @click="handleBatchIngest"
            >
              一键更新
            </el-button>
          </div>

          <div v-if="analysisReport" class="analysis-report">
            <h3>分析报告</h3>
            <el-alert
              :type="analysisReport.ready_for_ingest ? 'success' : 'warning'"
              :title="
                analysisReport.ready_for_ingest
                  ? '教材结构完整，可执行向量化'
                  : '教材存在问题，建议修复后再执行向量化'
              "
              :closable="false"
            />
            <div class="report-stats">
              <div class="stat-item">章节数: {{ analysisReport.chapter_count }}</div>
              <div class="stat-item">课程数: {{ analysisReport.lesson_count }}</div>
              <div class="stat-item">总字数: {{ analysisReport.total_chars }}</div>
              <div class="stat-item">
                平均章节字数: {{ analysisReport.avg_chars_per_chapter }}
              </div>
            </div>
            <div v-if="analysisReport.warnings.length > 0" class="report-warnings">
              <h4>警告</h4>
              <ul>
                <li v-for="(w, i) in analysisReport.warnings" :key="i">{{ w }}</li>
              </ul>
            </div>
            <div v-if="analysisReport.recommendations.length > 0" class="report-recommendations">
              <h4>建议</h4>
              <ul>
                <li v-for="(r, i) in analysisReport.recommendations" :key="i">{{ r }}</li>
              </ul>
            </div>
          </div>
        </div>

        <!-- 右侧：大纲预览 -->
        <div class="textbook-preview">
          <div v-if="outline" class="outline-tree">
            <div class="tree-header">
              <h3>{{ outline.title }}</h3>
              <p class="tree-overview">{{ outline.overview }}</p>
            </div>
            <div class="tree-chapters">
              <div v-for="ch in outline.chapters" :key="ch.index" class="tree-chapter">
                <div class="chapter-header" @click="toggleChapter(ch.index)">
                  <el-icon size="14">
                    <ArrowDown v-if="expandedChapters.includes(ch.index)" />
                    <ArrowRight v-else />
                  </el-icon>
                  <span>第{{ ch.index }}章 {{ ch.title }}</span>
                </div>
                <div v-show="expandedChapters.includes(ch.index)" class="chapter-lessons">
                  <div v-for="lesson in ch.lessons" :key="lesson.index" class="tree-lesson">
                    {{ lesson.index }}. {{ lesson.title }}
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="preview-empty">
            <el-empty description="选择一份大纲以预览内容" />
          </div>
        </div>
      </div>
    </div>
      </Transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, reactive, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Document, Lightning, MagicStick, ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import {
  adminApi,
  type TextbookItem,
  type AnalyzeReport,
  type TaskInfo,
} from '../api/client'
import { useModelStore } from '../stores/modelStore'

const textbooks = ref<TextbookItem[]>([])
const loading = ref(false)
const parsing = ref<Record<string, boolean>>({})
const ingesting = ref<Record<string, boolean>>({})
const tasks = ref<Record<string, any>>({})

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
const tableAreaRef = ref<HTMLDivElement>()
const tableHeight = ref(400)

function updateTableHeight() {
  if (tableAreaRef.value) {
    tableHeight.value = Math.max(tableAreaRef.value.clientHeight, 320)
  }
}

let resizeObserver: ResizeObserver | null = null


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

    window.dispatchEvent(new CustomEvent('refresh-tasks'))
    ElMessage.success('任务已提交，请在任务中心查看进度')
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

    window.dispatchEvent(new CustomEvent('refresh-tasks'))
    ElMessage.success('批量更新任务已提交，请在任务中心查看进度')
  } catch (e: any) {
    ElMessage.error(`提交失败: ${e.response?.data?.detail || e.message}`)
  }
}


// ── 智能采集 ──
const activeTab = ref('list')
const modelStore = useModelStore()
const selectedModelId = ref('')

const generateForm = reactive({
  subject: '语文',
  grade: '七年级',
  semester: '上册',
  publisher: '部编版',
  version_year: '2024',
  region: '全国通用',
  notes: '',
})

const selectedModel = computed(() => modelStore.getModelById(selectedModelId.value))

const outline = ref<Record<string, any> | null>(null)
const generatingOutline = ref(false)
const generateTaskId = ref('')

// 历史大纲选择
const outlineTasks = ref<TaskInfo[]>([])
const selectedOutlineTaskId = ref('')
const outlineOptions = computed(() =>
  outlineTasks.value.map((t) => ({
    task_id: t.task_id,
    label: `${(t.result as any)?.title || t.filename}（${formatTime(t.created_at)}）`,
  })),
)

watch(selectedOutlineTaskId, (id) => {
  const task = outlineTasks.value.find((t) => t.task_id === id)
  if (task?.result) {
    // 兼容旧数据：result 可能是 {status, outline} 包装或直接是大纲
    const raw = task.result as Record<string, any>
    outline.value = raw.outline ?? raw
  } else {
    outline.value = null
  }
})

async function loadOutlineTasks() {
  try {
    const { data } = await adminApi.listTasks({ skip: 0, limit: 100 })
    outlineTasks.value = (data.tasks || []).filter(
      (t: TaskInfo) => t.type === 'generate-outline' && t.status === 'completed' && t.result,
    )
  } catch {
    // 静默失败
  }
}
const generatedFile = ref('')
const analyzing = ref(false)
const analysisReport = ref<AnalyzeReport | null>(null)

const generateTask = computed(() => tasks.value[generateTaskId.value] || null)
const hasGenerateTask = computed(() => {
  const t = generateTask.value
  return t != null && (t.status === 'pending' || t.status === 'running')
})
const canGenerate = computed(() => outline.value != null && selectedModelId.value !== '')

const expandedChapters = ref<number[]>([])
function toggleChapter(index: number) {
  const pos = expandedChapters.value.indexOf(index)
  if (pos >= 0) {
    expandedChapters.value.splice(pos, 1)
  } else {
    expandedChapters.value.push(index)
  }
}

async function handleGenerateOutline() {
  if (!selectedModelId.value) {
    ElMessage.warning('请先选择模型')
    return
  }
  generatingOutline.value = true
  try {
    const { data } = await adminApi.generateOutline({
      subject: generateForm.subject,
      grade: generateForm.grade,
      semester: generateForm.semester,
      publisher: generateForm.publisher,
      version_year: generateForm.version_year,
      region: generateForm.region,
      notes: generateForm.notes,
      model_id: selectedModelId.value,
    })
    // 后台任务模式：创建任务后通过轮询获取结果
    tasks.value[data.task_id] = {
      task_id: data.task_id,
      type: 'generate-outline',
      filename: `${generateForm.publisher}${generateForm.version_year}${generateForm.grade}${generateForm.semester}${generateForm.subject}大纲`,
      status: 'pending',
      progress: 0,
      message: '等待执行',
      result: null,
    }
    ElMessage.info(`大纲生成任务已提交: ${data.task_id}，请在任务中心查看进度`)
    window.dispatchEvent(new CustomEvent('refresh-tasks'))
    // 提交后自动刷新历史大纲列表
    await loadOutlineTasks()
  } catch (e: any) {
    ElMessage.error(`提交失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    generatingOutline.value = false
  }
}

async function handleGenerateTextbook() {
  if (!outline.value) {
    ElMessage.warning('请选择一个教材大纲')
    return
  }
  if (!selectedModelId.value) {
    ElMessage.warning('请先选择模型')
    return
  }

  // 从选中的大纲任务中提取元数据（新格式包含 subject/grade 等）
  const task = outlineTasks.value.find((t) => t.task_id === selectedOutlineTaskId.value)
  let meta = {
    subject: generateForm.subject,
    grade: generateForm.grade,
    semester: generateForm.semester,
    publisher: generateForm.publisher,
    version_year: generateForm.version_year,
    region: generateForm.region,
  }
  if (task?.result) {
    const raw = task.result as Record<string, any>
    if (raw.subject) meta.subject = raw.subject
    if (raw.grade) meta.grade = raw.grade
    if (raw.semester) meta.semester = raw.semester
    if (raw.publisher) meta.publisher = raw.publisher
    if (raw.version_year) meta.version_year = raw.version_year
    if (raw.region !== undefined) meta.region = raw.region
  }

  try {
    const { data } = await adminApi.generateTextbook({
      outline: outline.value,
      ...meta,
      model_id: selectedModelId.value,
    })
    generateTaskId.value = data.task_id
    ElMessage.info(`教材生成任务已提交: ${data.task_id}`)

    tasks.value[data.task_id] = {
      task_id: data.task_id,
      type: 'generate',
      filename: `${generateForm.publisher}${generateForm.version_year}${generateForm.grade}${generateForm.semester}${generateForm.subject}`,
      status: 'pending',
      progress: 0,
      message: '等待执行',
      result: null,
    }

    window.dispatchEvent(new CustomEvent('refresh-tasks'))
    ElMessage.success('教材生成任务已提交，请在任务中心查看进度')
  } catch (e: any) {
    ElMessage.error(`提交失败: ${e.response?.data?.detail || e.message}`)
  }
}

async function handleAnalyze() {
  if (!generatedFile.value) {
    ElMessage.warning('请先生成教材')
    return
  }
  analyzing.value = true
  try {
    const { data } = await adminApi.analyzeTextbook(generatedFile.value)
    analysisReport.value = data.report
    if (data.report.ready_for_ingest) {
      ElMessage.success('教材分析通过，可以执行向量化')
    } else {
      ElMessage.warning('教材存在问题，请查看分析报告')
    }
  } catch (e: any) {
    ElMessage.error(`分析失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    analyzing.value = false
  }
}

function subjectClass(subject: string) {
  const map: Record<string, string> = {
    '语文': 'chinese',
    '数学': 'math',
    '英语': 'english',
    '科学': 'science',
    '社会': 'social',
  }
  return map[subject] || ''
}

function formatTime(ts: string) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// 令牌录入成功后（App.vue 全局弹窗处理）刷新本页数据
function onAdminTokenSaved() {
  loadData()
  modelStore.loadModels()
}

onMounted(() => {
  loadData()
  updateTableHeight()
  resizeObserver = new ResizeObserver(() => updateTableHeight())
  if (tableAreaRef.value) {
    resizeObserver.observe(tableAreaRef.value)
  }
  window.addEventListener('admin-token-saved', onAdminTokenSaved)
})

watch(activeTab, (tab) => {
  if (tab === 'generate' || tab === 'textbook') {
    modelStore.loadModels()
    loadOutlineTasks()
  }
  if (tab === 'list') {
    nextTick(() => {
      updateTableHeight()
      if (tableAreaRef.value) {
        resizeObserver?.disconnect()
        resizeObserver = new ResizeObserver(() => updateTableHeight())
        resizeObserver.observe(tableAreaRef.value)
      }
    })
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('admin-token-saved', onAdminTokenSaved)
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
.tab-content-area {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
  display: flex;
  flex-direction: column;
}
.tab-fade-enter-active,
.tab-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.tab-fade-enter-from,
.tab-fade-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
.subject-pill {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
}
.subject-pill.chinese { background: var(--subject-chinese); }
.subject-pill.math { background: var(--subject-math); }
.subject-pill.english { background: var(--subject-english); }
.subject-pill.science { background: var(--subject-science); }
.subject-pill.social { background: var(--subject-social); }
.action-btns {
  display: flex;
  gap: 6px;
  justify-content: center;
}
.admin-header {
  flex-shrink: 0;
  margin-bottom: 8px;
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
  margin-left: 4px;
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1.4;
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

/* Tab 切换 */
.tab-bar {
  flex-shrink: 0;
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border-light);
}
.tab-btn {
  padding: 8px 20px;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 14px;
  color: var(--text-secondary);
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}
.tab-btn:hover {
  color: var(--text-primary);
}
.tab-btn.active {
  color: var(--el-color-primary);
  border-bottom-color: var(--el-color-primary);
  font-weight: 500;
}

/* 智能采集面板 */
.generate-panel {
  flex: 1;
  overflow-y: auto;
  padding-right: 4px;
}
.gen-form {
  max-width: 900px;
}
.outline-selector {
  margin: 12px 0;
  max-width: 900px;
}
.gen-actions {
  margin: 16px 0;
  display: flex;
  gap: 12px;
}

/* 大纲预览 */
.outline-preview {
  margin-top: 16px;
  padding: 16px;
  background: var(--bg-card);
  border-radius: 8px;
  border: 1px solid var(--border-light);
}
.outline-preview h3 {
  margin: 0 0 12px;
  font-size: 16px;
  color: var(--text-primary);
}
.outline-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px;
}
.outline-overview {
  color: var(--text-secondary);
  font-size: 14px;
  margin: 0 0 16px;
  line-height: 1.6;
}
.outline-chapter {
  margin-bottom: 12px;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}
.chapter-title {
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 6px;
}
.lesson-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.lesson-tag {
  display: inline-block;
  padding: 2px 10px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border-radius: 4px;
  font-size: 13px;
}

/* 分析报告 */
.analysis-report {
  margin-top: 16px;
  padding: 16px;
  background: var(--bg-card);
  border-radius: 8px;
  border: 1px solid var(--border-light);
}
.analysis-report h3 {
  margin: 0 0 12px;
  font-size: 16px;
  color: var(--text-primary);
}
.report-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin: 12px 0;
}
.stat-item {
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-size: 14px;
  color: var(--text-secondary);
}
.report-warnings h4,
.report-recommendations h4 {
  margin: 12px 0 6px;
  font-size: 14px;
}
.report-warnings ul,
.report-recommendations ul {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.8;
}
.report-warnings li {
  color: var(--el-color-warning);
}
.report-recommendations li {
  color: var(--text-secondary);
}

/* 模型预览 */
.model-preview {
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.8;
}
.preview-item {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 表单卡片 */
.form-card {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-light);
  padding: 20px 24px;
  margin-bottom: 16px;
  max-width: 600px;
}
.form-card-title {
  margin: 0 0 16px;
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-light);
}

/* 主视觉生成按钮 */
.generate-main-btn {
  width: 100%;
  max-width: 600px;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: linear-gradient(135deg, var(--accent-primary) 0%, #143a6e 100%) !important;
  border: none !important;
  box-shadow: 0 4px 12px rgba(30, 74, 138, 0.3);
  transition: all var(--transition-base);
}
.generate-main-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(30, 74, 138, 0.4);
}

/* 教材生成左右分栏 */
.textbook-panel {
  padding-right: 0;
  overflow: hidden !important;
}
.textbook-layout {
  display: flex;
  gap: 20px;
  height: 100%;
  min-height: 0;
}
.textbook-sidebar {
  width: 380px;
  flex-shrink: 0;
  overflow-y: auto;
  padding-right: 4px;
}
.textbook-preview {
  flex: 1;
  min-width: 0;
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-light);
  overflow-y: auto;
  padding: 24px;
}

/* 大纲树形预览 */
.outline-tree {
  height: 100%;
}
.tree-header {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}
.tree-header h3 {
  margin: 0 0 8px;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}
.tree-overview {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.6;
}
.tree-chapters {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tree-chapter {
  border-radius: var(--radius-md);
  overflow: hidden;
}
.chapter-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  background: var(--el-fill-color-light);
  cursor: pointer;
  transition: background var(--transition-fast);
  border-radius: var(--radius-md);
}
.chapter-header:hover {
  background: var(--border-light);
}
.chapter-lessons {
  padding: 4px 0 4px 34px;
}
.tree-lesson {
  padding: 6px 0;
  font-size: 13px;
  color: var(--text-secondary);
  border-bottom: 1px dashed var(--border-light);
}
.tree-lesson:last-child {
  border-bottom: none;
}
.preview-empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
