import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import axios from 'axios'
import defaultSystemPrompt from '@/prompts/Agent_prompt.md?raw'

/** 与后端 ProviderRegistry 对齐的可选供应商 */
export const LLM_PROVIDER_IDS = ['qwen', 'deepseek', 'openrouter'] as const
export type LLMProvider = (typeof LLM_PROVIDER_IDS)[number]

export function normalizeProviderId(raw: string | undefined | null): LLMProvider {
  const p = (raw || '').trim()
  if (LLM_PROVIDER_IDS.includes(p as LLMProvider)) return p as LLMProvider
  return 'deepseek'
}

export interface ModelInfo {
  id: string
  name: string
  provider: string
  description: string
  max_tokens: number
  context_window?: number
  /** 来自 /models 的原始条目，用于能力合并（如 OpenRouter supported_parameters） */
  raw_meta?: Record<string, unknown> | null
}

export interface ModelCapability {
  supported: boolean
  min?: number
  max?: number
  default?: number | boolean | string
  step?: number
  choices?: string[]
  fixed?: number | boolean | string
  route?: string
}

export interface ModelCapabilities {
  temperature?: ModelCapability
  top_p?: ModelCapability
  top_k?: ModelCapability
  max_tokens?: ModelCapability
  frequency_penalty?: ModelCapability
  presence_penalty?: ModelCapability
  reasoning_effort?: ModelCapability
  web_search?: ModelCapability
  vision?: ModelCapability
}

export interface ParamControl {
  param_name: string
  label: string
  label_zh: string
  control_type: string
  enabled: boolean
  min?: number
  max?: number
  step?: number
  default?: number | boolean | string
  choices?: string[]
  fixed?: number | boolean | string
  help_text: string
}

// 与后端 LLMSettings 对齐的 snake_case 配置接口
export interface LLMConfig {
  provider: LLMProvider
  model: string
  api_key: string
  temperature: number
  max_tokens: number
  top_p: number
  top_k?: number | null
  frequency_penalty: number
  presence_penalty: number
  enable_online_search: boolean
  enable_reasoning: boolean
  reasoning_effort?: string | null
  system_prompt: string
  base_url: string
}

/** 与 GET /api/v1/llm/config/active 对齐 */
export interface LLMActiveConfigPublic {
  provider: string
  model: string
  temperature: number
  max_tokens: number
  top_p: number
  top_k?: number | null
  frequency_penalty: number
  presence_penalty: number
  enable_online_search: boolean
  enable_reasoning: boolean
  reasoning_effort?: string | null
  base_url?: string | null
  api_key_configured: boolean
  api_keys_present: Record<string, boolean>
}

const LLM_CONFIG_STORAGE_KEY = 'agent_framework_llm_config'
/** 各供应商独立 API Key（JSON 对象），替代旧的单槽 agent_framework_llm_apikey */
const LLM_API_KEYS_SESSION_KEY = 'agent_framework_llm_apikeys'
const LEGACY_LLM_API_KEY_KEY = 'agent_framework_llm_apikey'

function loadApiKeys(preferredProvider?: LLMProvider): Partial<Record<LLMProvider, string>> {
  const filterKeys = (o: Record<string, unknown>): Partial<Record<LLMProvider, string>> => {
    const out: Partial<Record<LLMProvider, string>> = {}
    for (const id of LLM_PROVIDER_IDS) {
      const v = o[id]
      if (typeof v === 'string' && v.trim()) out[id] = v
    }
    return out
  }
  try {
    const raw = sessionStorage.getItem(LLM_API_KEYS_SESSION_KEY)
    if (raw) {
      const o = JSON.parse(raw) as Record<string, unknown>
      if (o && typeof o === 'object') return filterKeys(o)
    }
  } catch {
    /* ignore */
  }
  try {
    const legacy = sessionStorage.getItem(LEGACY_LLM_API_KEY_KEY)
    if (legacy) {
      const p = normalizeProviderId(preferredProvider)
      const migrated = { [p]: legacy } as Partial<Record<LLMProvider, string>>
      sessionStorage.setItem(LLM_API_KEYS_SESSION_KEY, JSON.stringify(migrated))
      sessionStorage.removeItem(LEGACY_LLM_API_KEY_KEY)
      return migrated
    }
  } catch {
    /* ignore */
  }
  return {}
}

function saveApiKeys(keys: Partial<Record<LLMProvider, string>>) {
  try {
    sessionStorage.setItem(LLM_API_KEYS_SESSION_KEY, JSON.stringify(keys))
  } catch {
    /* ignore */
  }
}

/** 保存前规范化数字，避免 Element Plus 控件产生空字符串导致 422 */
function buildSanitizedSavePayload(cfg: LLMConfig): Record<string, unknown> {
  const num = (v: unknown, fallback: number) => {
    if (v === '' || v === null || v === undefined) return fallback
    const n = typeof v === 'number' ? v : Number(v)
    return Number.isFinite(n) ? n : fallback
  }
  const out: Record<string, unknown> = {
    provider: cfg.provider,
    model: cfg.model,
    // 注意：BYOK 模式下，API Key 绝不持久化到后端，
    // 仅通过 WebSocket 消息逐次随请求携带。此处刻意不发送 api_key。
    temperature: num(cfg.temperature, 0.2),
    max_tokens: Math.round(num(cfg.max_tokens, 2048)),
    top_p: num(cfg.top_p, 0.9),
    frequency_penalty: num(cfg.frequency_penalty, 0),
    presence_penalty: num(cfg.presence_penalty, 0),
    enable_online_search: Boolean(cfg.enable_online_search),
    enable_reasoning: Boolean(cfg.enable_reasoning)
  }
  const tk = cfg.top_k
  if (tk !== null && tk !== undefined) {
    const s = String(tk).trim()
    if (s !== '') {
      const ik = Math.round(num(tk, NaN))
      if (Number.isFinite(ik) && ik >= 1) out.top_k = ik
    }
  }
  if (cfg.reasoning_effort) out.reasoning_effort = cfg.reasoning_effort
  if (cfg.base_url) out.base_url = cfg.base_url
  return out
}

function loadConfig(): Partial<LLMConfig> {
  try {
    const stored = localStorage.getItem(LLM_CONFIG_STORAGE_KEY)
    if (stored) {
      const o = JSON.parse(stored) as Partial<LLMConfig>
      if (o.provider) o.provider = normalizeProviderId(o.provider as string)
      return o
    }
  } catch (e) {
    console.error('Failed to load LLM config:', e)
  }
  return {}
}

export const DEFAULT_SYSTEM_PROMPT = defaultSystemPrompt

export const useLLMStore = defineStore('llm', () => {
  const stored = loadConfig()
  const apiKeysByProvider = ref<Partial<Record<LLMProvider, string>>>(
    loadApiKeys(stored.provider as LLMProvider | undefined)
  )

  // State
  const config = ref<LLMConfig>({
    provider: 'deepseek',
    model: 'deepseek-v4-flash',
    api_key: '',
    temperature: 0.2,
    max_tokens: 8192,
    top_p: 0.9,
    top_k: null,
    frequency_penalty: 0,
    presence_penalty: 0,
    enable_online_search: false,
    enable_reasoning: false,
    reasoning_effort: null,
    system_prompt: DEFAULT_SYSTEM_PROMPT,
    base_url: ''
  })

  const availableModels = ref<ModelInfo[]>([])
  const isLoading = ref(false)
  const capabilities = ref<ModelCapabilities | null>(null)
  const paramControls = ref<ParamControl[]>([])
  const isTesting = ref(false)
  const testResult = ref<{ success: boolean; message: string; latency_ms?: number } | null>(null)
  const showConfigPanel = ref(false)

  function applyProviderApiKey() {
    const p = config.value.provider
    config.value.api_key = apiKeysByProvider.value[p] || ''
  }

  function panelParamToConfigKey(paramName: string): keyof LLMConfig {
    if (paramName === 'web_search') return 'enable_online_search'
    return paramName as keyof LLMConfig
  }

  /** 切换模型后按能力表修正/钳位参数 */
  function applyConfigFromCapabilities(
    controls: ParamControl[],
    caps: ModelCapabilities | null,
    modelMaxTokens?: number
  ) {
    const cfg = config.value
    const num = (v: unknown, fb: number) => {
      if (v === '' || v === null || v === undefined) return fb
      const n = typeof v === 'number' ? v : Number(v)
      return Number.isFinite(n) ? n : fb
    }

    for (const ctrl of controls) {
      const key = panelParamToConfigKey(ctrl.param_name)

      if (!ctrl.enabled) {
        if (key === 'top_k') cfg.top_k = null
        else if (key === 'enable_online_search') cfg.enable_online_search = false
        else if (key === 'reasoning_effort') cfg.reasoning_effort = null
        continue
      }

      if (ctrl.fixed !== undefined) {
        ;(cfg as Record<string, unknown>)[key] = ctrl.fixed
        continue
      }

      if (ctrl.control_type === 'slider' || ctrl.control_type === 'number') {
        const defRaw = ctrl.default
        const def =
          defRaw !== undefined && defRaw !== null && defRaw !== ''
            ? num(defRaw, 0)
            : undefined
        let val = num((cfg as Record<string, unknown>)[key], def ?? 0)
        if (ctrl.min !== undefined) val = Math.max(ctrl.min, val)
        if (ctrl.max !== undefined) val = Math.min(ctrl.max, val)
        if (key === 'max_tokens') {
          if (modelMaxTokens) val = Math.min(val, modelMaxTokens)
          cfg.max_tokens = Math.round(val)
        } else if (key === 'top_k') {
          cfg.top_k = Math.round(val)
        } else {
          ;(cfg as Record<string, unknown>)[key] = val
        }
        continue
      }

      if (ctrl.control_type === 'select' && key === 'reasoning_effort') {
        const cur = cfg.reasoning_effort
        if (!cur || !ctrl.choices?.includes(cur)) {
          cfg.reasoning_effort =
            (typeof ctrl.default === 'string' ? ctrl.default : null) ??
            ctrl.choices?.[0] ??
            null
        }
      }
    }

    if (!(cfg.provider === 'deepseek' && cfg.model.startsWith('deepseek-v4'))) {
      cfg.enable_reasoning = false
    }
    if (caps?.top_k && !caps.top_k.supported) {
      cfg.top_k = null
    }
  }

  // 页面加载时合并本地存储
  if (stored.provider) config.value.provider = normalizeProviderId(stored.provider as string)
  if (stored.model) config.value.model = stored.model
  if (stored.temperature !== undefined) config.value.temperature = stored.temperature
  if (stored.max_tokens !== undefined) config.value.max_tokens = stored.max_tokens
  if (stored.top_p !== undefined) config.value.top_p = stored.top_p
  if (stored.top_k !== undefined) config.value.top_k = stored.top_k
  if (stored.frequency_penalty !== undefined) config.value.frequency_penalty = stored.frequency_penalty
  if (stored.presence_penalty !== undefined) config.value.presence_penalty = stored.presence_penalty
  if (stored.enable_online_search !== undefined) config.value.enable_online_search = stored.enable_online_search
  if (stored.enable_reasoning !== undefined) config.value.enable_reasoning = stored.enable_reasoning
  if (stored.base_url !== undefined) config.value.base_url = stored.base_url

  applyProviderApiKey()

  const saveLocal = () => {
    try {
      const { api_key, system_prompt: _sp, ...rest } = config.value
      localStorage.setItem(LLM_CONFIG_STORAGE_KEY, JSON.stringify(rest))
      saveApiKeys(apiKeysByProvider.value)
    } catch (e) {
      console.error('Failed to save LLM config:', e)
    }
  }

  watch(
    () => config.value.provider,
    () => {
      applyProviderApiKey()
    }
  )

  watch(
    () => config.value.api_key,
    v => {
      const p = config.value.provider
      apiKeysByProvider.value = { ...apiKeysByProvider.value, [p]: v }
      saveApiKeys(apiKeysByProvider.value)
    }
  )

  // 供应商 / 模型变更立即写入本地，减少多标签页状态漂移
  watch(
    () => [config.value.provider, config.value.model] as const,
    () => {
      saveLocal()
    }
  )

  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (e: StorageEvent) => {
      if (e.key !== LLM_CONFIG_STORAGE_KEY || !e.newValue) return
      try {
        const partial = JSON.parse(e.newValue) as Partial<LLMConfig>
        if (partial.provider !== undefined) {
          config.value.provider = normalizeProviderId(partial.provider as string)
        }
        if (partial.model !== undefined) config.value.model = partial.model
        if (partial.temperature !== undefined) config.value.temperature = partial.temperature
        if (partial.max_tokens !== undefined) config.value.max_tokens = partial.max_tokens
        if (partial.top_p !== undefined) config.value.top_p = partial.top_p
        if (partial.top_k !== undefined) config.value.top_k = partial.top_k
        if (partial.frequency_penalty !== undefined) {
          config.value.frequency_penalty = partial.frequency_penalty
        }
        if (partial.presence_penalty !== undefined) {
          config.value.presence_penalty = partial.presence_penalty
        }
        if (partial.enable_online_search !== undefined) {
          config.value.enable_online_search = partial.enable_online_search
        }
        if (partial.enable_reasoning !== undefined) {
          config.value.enable_reasoning = partial.enable_reasoning
        }
        if (partial.base_url !== undefined) config.value.base_url = partial.base_url || ''
        applyProviderApiKey()
      } catch {
        /* ignore */
      }
    })
  }

  // Getters
  const getProviderName = (provider: LLMProvider) => {
    const names: Record<LLMProvider, string> = {
      qwen: '通义千问',
      deepseek: 'DeepSeek',
      openrouter: 'OpenRouter'
    }
    return names[provider]
  }

  const getModelsByProvider = (provider: LLMProvider) => {
    return availableModels.value.filter(m => m.provider === provider)
  }

  const isParamSupported = (paramName: string): boolean => {
    const cap = (capabilities.value as any)?.[paramName]
    return cap ? cap.supported : false
  }

  const getParamFixedValue = (paramName: string): number | boolean | string | undefined => {
    const cap = (capabilities.value as any)?.[paramName]
    return cap ? cap.fixed : undefined
  }

  // Actions
  const fetchModels = async () => {
    try {
      isLoading.value = true
      const response = await axios.get('/api/v1/llm/models')
      const models: ModelInfo[] = []
      response.data.forEach((p: any) => {
        models.push(...p.models)
      })
      availableModels.value = models
    } catch (error) {
      console.error('获取模型列表失败:', error)
      // 兜底内置模型
      availableModels.value = [
        { id: 'qwen-max', name: '通义千问-Max', provider: 'qwen', description: '通义千问系列最强模型', max_tokens: 8192 },
        { id: 'qwen-plus', name: '通义千问-Plus', provider: 'qwen', description: '性能均衡', max_tokens: 8192 },
        { id: 'qwen-turbo', name: '通义千问-Turbo', provider: 'qwen', description: '快速响应', max_tokens: 4096 },
        { id: 'deepseek-chat', name: 'DeepSeek-V3', provider: 'deepseek', description: '通用对话模型', max_tokens: 8192 },
        { id: 'deepseek-reasoner', name: 'DeepSeek-R1', provider: 'deepseek', description: '深度推理模型', max_tokens: 8192 },
        { id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash', provider: 'deepseek', description: 'V4 快速（平台默认）', max_tokens: 8192 },
        { id: 'deepseek-v4-pro', name: 'DeepSeek V4 Pro', provider: 'deepseek', description: 'V4 强模型', max_tokens: 8192 },
        {
          id: 'openai/gpt-4o',
          name: 'GPT-4o (OpenRouter)',
          provider: 'openrouter',
          description: 'OpenRouter 路由',
          max_tokens: 8192
        },
        {
          id: 'anthropic/claude-3.5-sonnet',
          name: 'Claude 3.5 Sonnet (OpenRouter)',
          provider: 'openrouter',
          description: 'OpenRouter 路由',
          max_tokens: 8192
        }
      ]
    } finally {
      isLoading.value = false
    }
  }

  const fetchLiveModels = async (provider: LLMProvider, apiKey: string, baseUrl?: string) => {
    try {
      isLoading.value = true
      const params: any = { provider, api_key: apiKey }
      if (baseUrl) params.base_url = baseUrl
      const response = await axios.get('/api/v1/llm/models/live', { params })
      if (response.data && response.data.length > 0) {
        const models: ModelInfo[] = []
        response.data.forEach((p: any) => {
          models.push(...p.models)
        })
        availableModels.value = [
          ...availableModels.value.filter(m => m.provider !== provider),
          ...models
        ]
      }
      return true
    } catch (error) {
      console.error('实时拉取模型列表失败:', error)
      return false
    } finally {
      isLoading.value = false
    }
  }

  const fetchCapabilities = async (provider: LLMProvider, model: string) => {
    try {
      const rawMeta =
        availableModels.value.find(m => m.id === model && m.provider === provider)?.raw_meta ?? undefined
      const response = await axios.post('/api/v1/llm/capabilities/lookup', {
        provider,
        model,
        ...(rawMeta && Object.keys(rawMeta).length > 0 ? { raw_meta: rawMeta } : {})
      })
      capabilities.value = response.data.capabilities
      paramControls.value = response.data.controls
      const modelInfo = availableModels.value.find(
        m => m.id === model && m.provider === provider
      )
      applyConfigFromCapabilities(
        paramControls.value,
        capabilities.value,
        modelInfo?.max_tokens
      )
      return response.data
    } catch (error) {
      console.error('获取能力表失败:', error)
      capabilities.value = null
      paramControls.value = []
      return null
    }
  }

  const testConnection = async () => {
    try {
      isTesting.value = true
      testResult.value = null
      const response = await axios.post('/api/v1/llm/test-connection', {
        provider: config.value.provider,
        model: config.value.model,
        api_key: config.value.api_key,
        base_url: config.value.base_url || undefined
      })
      testResult.value = {
        success: response.data.success,
        message: response.data.message,
        latency_ms: response.data.latency_ms
      }
      // 如果后端返回了建议的能力表，更新本地
      if (response.data.capabilities) {
        capabilities.value = response.data.capabilities
      }
      return response.data
    } catch (error) {
      console.error('测试连接失败:', error)
      testResult.value = { success: false, message: '测试连接请求失败' }
      return null
    } finally {
      isTesting.value = false
    }
  }

  const saveConfigToServer = async () => {
    try {
      const payload = buildSanitizedSavePayload(config.value)
      const response = await axios.post('/api/v1/llm/config', payload)
      if (response.data.success) {
        saveLocal()
      }
      return response.data
    } catch (error: unknown) {
      console.error('保存配置失败:', error)
      const ax = error as {
        response?: { data?: { detail?: unknown }; status?: number }
      }
      const detail = ax.response?.data?.detail
      let message = '保存失败'
      if (Array.isArray(detail)) {
        message = detail
          .map((d: { msg?: string; loc?: unknown }) => d.msg || JSON.stringify(d))
          .join('；')
      } else if (typeof detail === 'string') {
        message = detail
      } else if (detail && typeof detail === 'object') {
        message = JSON.stringify(detail)
      }
      return { success: false, message, config: null }
    }
  }

  const hydrateActiveConfigFromServer = async () => {
    try {
      // 已有本地偏好的用户（曾在本浏览器设置过模型/参数）不再被服务端全局配置覆盖，
      // 避免公网多用户场景下"别人改了平台配置、刷新后我的选择被顶掉"。
      // 仅首次访问（无 localStorage 记录）时用服务端平台默认兜底。
      let hasLocalPreference = false
      try {
        hasLocalPreference = !!localStorage.getItem(LLM_CONFIG_STORAGE_KEY)
      } catch {
        /* ignore */
      }
      const { data } = await axios.get<LLMActiveConfigPublic>('/api/v1/llm/config/active')
      if (!data) return
      if (hasLocalPreference) return
      if (data.provider) config.value.provider = normalizeProviderId(data.provider)
      if (data.model) config.value.model = data.model
      config.value.temperature = data.temperature
      config.value.max_tokens = data.max_tokens
      config.value.top_p = data.top_p
      config.value.top_k = data.top_k ?? null
      config.value.frequency_penalty = data.frequency_penalty
      config.value.presence_penalty = data.presence_penalty
      config.value.enable_online_search = data.enable_online_search
      config.value.enable_reasoning = data.enable_reasoning
      config.value.reasoning_effort = data.reasoning_effort ?? null
      config.value.base_url = (data.base_url as string) || ''
      applyProviderApiKey()
    } catch (e) {
      console.error('拉取服务端 LLM 全局配置失败:', e)
    }
  }

  const syncConfigFromServer = async () => {
    try {
      const response = await axios.get('/api/v1/llm/config/default')
      const data = response.data
      // 仅同步后端仓库中的系统提示词，不覆盖用户本地的供应商/模型/密钥等选择
      if (data.system_prompt) config.value.system_prompt = data.system_prompt
    } catch (error) {
      console.error('同步配置失败:', error)
    }
  }

  const updateConfig = async (partial: Partial<LLMConfig>) => {
    Object.assign(config.value, partial)
    await saveConfigToServer()
  }

  /**
   * 为指定供应商写入 API Key（仅 sessionStorage，按标签页隔离）。
   * 若设置的是当前选中的供应商，同步更新 config.api_key。
   */
  const setApiKeyForProvider = (p: LLMProvider, key: string) => {
    apiKeysByProvider.value = { ...apiKeysByProvider.value, [p]: key }
    saveApiKeys(apiKeysByProvider.value)
    if (config.value.provider === p) {
      config.value.api_key = key
    }
  }

  /** 退出当前会话：清除当前标签页内的所有 API Key */
  const clearAllApiKeys = () => {
    apiKeysByProvider.value = {}
    config.value.api_key = ''
    try {
      sessionStorage.removeItem(LLM_API_KEYS_SESSION_KEY)
    } catch {
      /* ignore */
    }
  }

  const toggleConfigPanel = () => {
    showConfigPanel.value = !showConfigPanel.value
  }

  return {
    config,
    apiKeysByProvider,
    availableModels,
    isLoading,
    capabilities,
    paramControls,
    isTesting,
    testResult,
    showConfigPanel,
    getProviderName,
    getModelsByProvider,
    isParamSupported,
    getParamFixedValue,
    saveLocal,
    fetchModels,
    fetchLiveModels,
    fetchCapabilities,
    testConnection,
    saveConfigToServer,
    syncConfigFromServer,
    hydrateActiveConfigFromServer,
    updateConfig,
    setApiKeyForProvider,
    clearAllApiKeys,
    toggleConfigPanel
  }
})
