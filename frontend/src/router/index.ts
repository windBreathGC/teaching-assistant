import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ChatView from '../views/ChatView.vue'
import QuizView from '../views/QuizView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/chat/:subject?', name: 'chat', component: ChatView, props: true },
    { path: '/quiz', name: 'quiz', component: QuizView },
  ],
})

export default router
