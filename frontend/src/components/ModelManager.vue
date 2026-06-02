<template>
  <el-drawer
    v-model="store.dialogVisible"
    title="模型接入管理"
    :size="drawerSize"
    :with-header="true"
    :close-on-click-modal="false"
  >
    <template #header>
      <div class="drawer-header">
        <span>模型接入管理</span>
        <div class="header-actions">
          <el-button :icon="Refresh" @click="store.loadModels()" title="刷新" link></el-button>
          <el-button :icon="isMaximized ? CopyDocument : FullScreen" @click="toggleMaximize" :title="isMaximized ? '还原' : '最大化'" link></el-button>
          <el-button :icon="Plus" @click="startAdd" title="添加模型" link></el-button>
        </div>
      </div>
    </template>

    <div class="model-content">
      <div class="model-list-wrapper">
        <div class="model-list-header">
          <span class="col-name">名称</span>
          <span class="col-model">模型</span>
          <span class="col-default">默认</span>
          <span class="col-url">API 地址</span>
          <span class="col-actions">操作</span>
        </div>
        <div class="model-list-container">
          <el-empty v-if="paginatedModels.length === 0" description="暂无模型配置" />
          <div
            v-for="model in paginatedModels"
            :key="model.id"
            class="model-item"
            :class="{ default: model.is_default }"
          >
            <span class="col-name">{{ model.name }}</span>
            <span class="col-model" :title="model.model_name">{{ model.model_name }}</span>
            <span class="col-default">
              <el-tag v-if="model.is_default" type="success" size="small">默认</el-tag>
            </span>
            <span class="col-url" :title="model.base_url">{{ model.base_url }}</span>
            <span class="col-actions">
              <el-button
                v-if="!model.is_default"
                link
                type="primary"
                size="small"
                @click="store.setDefault(model.id)"
              >
                设为默认
              </el-button>
              <el-button link type="primary" size="small" @click="startEdit(model)">
                编辑
              </el-button>
              <el-button link type="danger" size="small" @click="handleDelete(model.id)">
                删除
              </el-button>
            </span>
          </div>
        </div>
      </div>
      <div class="pagination-area">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[5, 10, 20, 50]"
          :total="store.models.length"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handleSizeChange"
        />
      </div>
    </div>

    <!-- 添加/编辑表单 -->
    <el-dialog
      v-model="formVisible"
      :title="isEdit ? '编辑模型' : '添加模型'"
      width="480px"
      append-to-body
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="90px" :rules="rules" ref="formRef">
        <el-form-item label="显示名称" prop="name">
          <el-input v-model="form.name" placeholder="如：OpenAI GPT-4o" />
        </el-form-item>
        <el-form-item label="API地址" prop="base_url">
          <el-input v-model="form.base_url" placeholder="https://api.openai.com/v1" />
        </el-form-item>
        <el-form-item label="API密钥" prop="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            :placeholder="isEdit ? '留空表示不修改' : 'sk-...'"
          />
        </el-form-item>
        <el-form-item label="模型名称" prop="model_name">
          <el-input v-model="form.model_name" placeholder="gpt-4o-mini" />
        </el-form-item>
        <el-form-item label="温度">
          <el-slider v-model="form.temperature" :min="0" :max="1" :step="0.1" />
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="form.is_default" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Plus, Refresh, FullScreen, CopyDocument } from '@element-plus/icons-vue'
import { useModelStore, type ModelProvider } from '../stores/modelStore'

const store = useModelStore()
const isMaximized = ref(false)
const drawerSize = computed(() => isMaximized.value ? '100%' : '720px')
const formVisible = ref(false)
const isEdit = ref(false)
const editingId = ref('')
const formRef = ref()

const currentPage = ref(1)
const pageSize = ref(10)

const paginatedModels = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return store.models.slice(start, start + pageSize.value)
})

function handleSizeChange() {
  currentPage.value = 1
}

const form = reactive({
  name: '',
  base_url: 'https://api.openai.com/v1',
  api_key: '',
  model_name: 'gpt-4o-mini',
  temperature: 0.3,
  is_default: false,
})

const rules = computed(() => ({
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  base_url: [{ required: true, message: '请输入API地址', trigger: 'blur' }],
  api_key: [{ required: !isEdit.value, message: '请输入API密钥', trigger: 'blur' }],
  model_name: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
}))

function resetForm() {
  form.name = ''
  form.base_url = 'https://api.openai.com/v1'
  form.api_key = ''
  form.model_name = 'gpt-4o-mini'
  form.temperature = 0.3
  form.is_default = false
}

function toggleMaximize() {
  isMaximized.value = !isMaximized.value
}

function startAdd() {
  isEdit.value = false
  editingId.value = ''
  resetForm()
  formVisible.value = true
}

function startEdit(row: ModelProvider) {
  isEdit.value = true
  editingId.value = row.id
  form.name = row.name
  form.base_url = row.base_url
  form.api_key = row.api_key
  form.model_name = row.model_name
  form.temperature = row.temperature
  form.is_default = row.is_default
  formVisible.value = true
}

async function submitForm() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  const payload: any = { ...form }
  if (isEdit.value && !payload.api_key) {
    delete payload.api_key
  }

  if (isEdit.value) {
    await store.updateModel(editingId.value, payload)
  } else {
    await store.addModel(payload)
  }
  formVisible.value = false
}

async function handleDelete(id: string) {
  try {
    await ElMessageBox.confirm('确定删除该模型配置吗？', '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await store.deleteModel(id)
  } catch {
    // cancel
  }
}
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

.model-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 12px 16px;
  box-sizing: border-box;
}

.model-list-wrapper {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.model-list-header {
  display: grid;
  grid-template-columns: 1fr 200px 60px 1fr 180px;
  gap: 8px;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--el-fill-color-light);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}

.model-list-container {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.model-item {
  display: grid;
  grid-template-columns: 1fr 200px 60px 1fr 180px;
  gap: 8px;
  padding: 10px 12px;
  align-items: center;
  border-bottom: 1px solid var(--border-light);
  font-size: 12px;
  transition: background 0.15s;
}

.model-item:hover {
  background: var(--el-fill-color-light);
}

.model-item.default {
  border-left: 3px solid var(--el-color-success);
  padding-left: 9px;
}

.col-name {
  color: var(--text-primary);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.col-model {
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.col-url {
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.col-default {
  display: flex;
  align-items: center;
  justify-content: center;
}

.col-actions {
  display: flex;
  gap: 4px;
  justify-self: end;
}

.pagination-area {
  flex-shrink: 0;
  padding-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
