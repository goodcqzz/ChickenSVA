import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/HomeView.vue')
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue')
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { requiresUserAuth: true }
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach(async (to, _from, next) => {
  const auth = useAuthStore()
  if (!auth.configLoaded) {
    try {
      await auth.fetchPublicConfig()
    } catch {
      auth.configLoaded = true
    }
  }
  if (to.path === '/login' && auth.authUsersEnabled && auth.isAuthenticated()) {
    next({ path: '/chat' })
    return
  }
  if (to.meta.requiresUserAuth && auth.authUsersEnabled && !auth.isAuthenticated()) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }
  next()
})

export default router
