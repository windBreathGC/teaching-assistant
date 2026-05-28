<template>
  <div class="chat-view">
    <aside class="sidebar" :class="{ 'mobile-open': store.sidebarVisible, collapsed: store.sidebarCollapsed }">
      <SubjectTree />
    </aside>
    <div
      v-if="store.sidebarVisible"
      class="sidebar-overlay"
      @click="store.closeSidebar()"
    />
    <main class="chat-main">
      <ChatWindow />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useAppStore } from '../stores/app'
import SubjectTree from '../components/SubjectTree.vue'
import ChatWindow from '../components/ChatWindow.vue'

const store = useAppStore()
</script>

<style scoped>
.chat-view {
  display: flex;
  height: calc(100vh - 60px);
}
.sidebar {
  width: 280px;
  background: var(--bg-card);
  border-right: 1px solid var(--border-light);
  overflow-y: auto;
  flex-shrink: 0;
  transition: width 0.25s ease;
}
.sidebar.collapsed {
  width: 0;
  overflow: hidden;
  border-right: none;
}
.chat-main {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.sidebar-overlay {
  display: none;
}

@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    top: 60px;
    left: 0;
    bottom: 0;
    z-index: 100;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    box-shadow: var(--shadow-lg);
  }
  .sidebar.mobile-open {
    transform: translateX(0);
  }
  .sidebar-overlay {
    display: block;
    position: fixed;
    top: 60px;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.35);
    z-index: 99;
  }
}
</style>
