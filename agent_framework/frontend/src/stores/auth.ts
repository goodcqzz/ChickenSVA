import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'

const SESSION_TOKEN_KEY = 'user_session_token'

export const useAuthStore = defineStore('auth', () => {
  /** 是否已从后端拉取公开配置 */
  const configLoaded = ref(false)

  /** 是否要求用户登录才能访问 /chat（公网模式下可开启） */
  const authUsersEnabled = ref(false)

  /** 后端是否配置了默认模型 Key（供所有用户免费使用） */
  const hasDefaultModel = ref(true)

  /** 当前 IP 的平台默认模型每日剩余配额 */
  const dailyRemaining = ref<number | null>(null)
  const dailyQuota = ref<number | null>(null)
  /** 平台默认模型 burst 限额（5 分钟窗口） */
  const burstLimit = ref<number | null>(null)
  const burstWindowSeconds = ref<number | null>(null)
  const burstRemaining = ref<number | null>(null)

  /** 后端 DEBUG=true 时前端可展示 LLM 开发者选项 */
  const debugMode = ref(false)

  async function fetchPublicConfig() {
    try {
      const res = await axios.get('/api/v1/public-config')
      authUsersEnabled.value = res.data.auth_users_enabled ?? false
      hasDefaultModel.value = res.data.has_default_model ?? true
      debugMode.value = res.data.debug ?? false
      dailyQuota.value = res.data.default_model_daily_quota ?? null
      burstLimit.value = res.data.default_model_burst_limit ?? null
      burstWindowSeconds.value = res.data.default_model_burst_window_seconds ?? null
    } catch {
      // 接口不可达时保持安全默认：不要求登录
    } finally {
      configLoaded.value = true
    }
  }

  /** 查询当前 IP 平台默认模型剩余配额（含 burst） */
  async function fetchQuota() {
    try {
      const res = await axios.get('/api/v1/quota')
      dailyRemaining.value = res.data?.remaining ?? null
      if (res.data?.quota != null) dailyQuota.value = res.data.quota
      burstRemaining.value = res.data?.burst_remaining ?? null
      if (res.data?.burst_limit != null) burstLimit.value = res.data.burst_limit
      if (res.data?.burst_window_seconds != null) {
        burstWindowSeconds.value = res.data.burst_window_seconds
      }
    } catch {
      // 接口不可用时静默忽略
    }
  }

  /**
   * 检测当前浏览器 session 是否有效（key 存在即视为已认证）。
   * sessionStorage 关闭标签页自动清除，天然隔离多用户。
   */
  function isAuthenticated(): boolean {
    return !!sessionStorage.getItem(SESSION_TOKEN_KEY)
  }

  /** 写入 session token（仅 sessionStorage，不持久化） */
  function setSession(token: string) {
    sessionStorage.setItem(SESSION_TOKEN_KEY, token)
  }

  /** 清除 session（退出登录） */
  function clearSession() {
    sessionStorage.removeItem(SESSION_TOKEN_KEY)
  }

  return {
    configLoaded,
    authUsersEnabled,
    hasDefaultModel,
    dailyRemaining,
    dailyQuota,
    burstLimit,
    burstWindowSeconds,
    burstRemaining,
    debugMode,
    fetchPublicConfig,
    fetchQuota,
    isAuthenticated,
    setSession,
    clearSession,
  }
})
