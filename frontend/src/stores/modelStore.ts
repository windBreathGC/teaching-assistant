import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi, type ModelProvider } from '../api/client'

export { type ModelProvider }

export const useModelStore = defineStore('models', () => {
  const models = ref<ModelProvider[]>([])
  const dialogVisible = ref(false)
  const loading = ref(false)

  const defaultModel = computed(() =>
    models.value.find((m) => m.is_default) || models.value[0] || null,
  )

  const modelOptions = computed(() =>
    models.value.map((m) => ({
      label: m.name + (m.is_default ? ' (默认)' : ''),
      value: m.id,
    })),
  )

  async function loadModels() {
    loading.value = true
    try {
      const { data } = await adminApi.listModels()
      models.value = data.models || []
    } catch (e: any) {
      ElMessage.error('加载模型配置失败')
    } finally {
      loading.value = false
    }
  }

  async function addModel(data: Omit<ModelProvider, 'id'>): Promise<ModelProvider | null> {
    try {
      const { data: resp } = await adminApi.addModel(data)
      models.value.push(resp.model)
      ElMessage.success('添加成功')
      return resp.model
    } catch (e: any) {
      ElMessage.error(`添加失败: ${e.response?.data?.detail || e.message}`)
      return null
    }
  }

  async function updateModel(id: string, data: Partial<Omit<ModelProvider, 'id'>>) {
    try {
      const { data: resp } = await adminApi.updateModel(id, data)
      const idx = models.value.findIndex((m) => m.id === id)
      if (idx !== -1) {
        models.value[idx] = resp.model
      }
      ElMessage.success('更新成功')
    } catch (e: any) {
      ElMessage.error(`更新失败: ${e.response?.data?.detail || e.message}`)
    }
  }

  async function deleteModel(id: string) {
    try {
      await adminApi.deleteModel(id)
      models.value = models.value.filter((m) => m.id !== id)
      ElMessage.success('删除成功')
    } catch (e: any) {
      ElMessage.error(`删除失败: ${e.response?.data?.detail || e.message}`)
    }
  }

  async function setDefault(id: string) {
    try {
      await adminApi.setDefaultModel(id)
      models.value.forEach((m) => { m.is_default = m.id === id })
    } catch (e: any) {
      ElMessage.error(`设置默认失败: ${e.response?.data?.detail || e.message}`)
    }
  }

  function getModelById(id: string): ModelProvider | null {
    return models.value.find((m) => m.id === id) || null
  }

  function openDialog() {
    dialogVisible.value = true
    loadModels()
  }

  function closeDialog() {
    dialogVisible.value = false
  }

  return {
    models,
    dialogVisible,
    loading,
    defaultModel,
    modelOptions,
    loadModels,
    addModel,
    updateModel,
    deleteModel,
    setDefault,
    getModelById,
    openDialog,
    closeDialog,
  }
})
