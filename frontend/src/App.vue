<template>
  <div class="app-container">
    <header class="app-header">
      <div class="header-left" @click="$router.push('/')">
        <div class="logo-icon">
          <el-icon size="22"><School /></el-icon>
        </div>
        <span class="app-title">中学伴学助教</span>
      </div>
      <nav class="header-nav">
        <button
          class="nav-btn"
          :class="{ active: $route.name === 'home' }"
          @click="$router.push('/')"
        >
          <el-icon size="16"><HomeFilled /></el-icon>
          <span>课程首页</span>
        </button>
        <button
          v-if="currentSubject"
          class="nav-btn"
          :class="{ active: $route.name === 'chat' }"
          @click="$router.push({ name: 'chat', params: { subject: currentSubject.id } })"
        >
          <el-icon size="16"><ChatLineRound /></el-icon>
          <span>{{ currentSubject.name }}</span>
        </button>
      </nav>
    </header>
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { School, HomeFilled, ChatLineRound } from '@element-plus/icons-vue'
import { useAppStore } from './stores/app'

const route = useRoute()
const store = useAppStore()
const currentSubject = computed(() => store.currentSubject)

watch(() => route.path, (path) => {
  if (path === '/') {
    store.selectSubject(null)
  }
})
</script>

<style scoped>
.app-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-base);
}
.app-header {
  height: 60px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-8);
  flex-shrink: 0;
  position: relative;
  z-index: 10;
}
.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  cursor: pointer;
  transition: opacity var(--transition-fast);
}
.header-left:hover {
  opacity: 0.7;
}
.logo-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--accent-primary);
  color: var(--text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
}
.app-title {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}
.header-nav {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.nav-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.nav-btn:hover {
  background: var(--bg-hover);
  color: var(--text-secondary);
}
.nav-btn.active {
  background: var(--accent-primary-light);
  color: var(--accent-primary);
}
.app-main {
  flex: 1;
  overflow: auto;
}
</style>
