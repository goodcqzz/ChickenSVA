<template>
  <div class="llm-config-panel-overlay" @click.self="$emit('close')">
    <div class="llm-config-panel">
      <div class="panel-header">
        <h3 class="panel-title">
          <el-icon><Setting /></el-icon>
          Model Settings
        </h3>
        <el-button text circle @click="$emit('close')">
          <el-icon><Close /></el-icon>
        </el-button>
      </div>

      <div class="panel-content">
        <el-form label-position="top" size="default">
          <!-- 产品层：用户只需选模型 -->
          <el-form-item label="Provider">
            <el-radio-group v-model="llmStore.config.provider" @change="onProviderChange">
              <el-radio-button label="qwen">Qwen</el-radio-button>
              <el-radio-button label="deepseek">DeepSeek</el-radio-button>
              <el-radio-button label="openrouter">OpenRouter</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="Model">
            <el-select
              v-model="llmStore.config.model"
              @change="onModelChange"
              style="width: 100%"
              filterable
            >
              <el-option
                v-for="model in modelsForProvider"
                :key="model.id"
                :label="model.name"
                :value="model.id"
              >
                <div class="model-option">
                  <span>{{ model.name }}</span>
                  <el-tag size="small" type="info">{{ model.max_tokens }} tokens</el-tag>
                </div>
              </el-option>
            </el-select>
            <p v-if="selectedModelInfo?.description" class="model-description">
              {{ selectedModelInfo.description }}
            </p>
          </el-form-item>

          <el-form-item label="API Key (optional)">
            <el-input
              v-model="llmStore.config.api_key"
              type="password"
              show-password
              placeholder="Leave empty to use platform free model"
            />
            <p class="help-text">
              <template v-if="auth.hasDefaultModel">
                Without a key, the platform free model is used (daily quota applies).
              </template>
              With a key (BYOK): stored in this tab's sessionStorage only — never persisted on the server.
            </p>
          </el-form-item>

          <el-form-item v-if="isDeepSeekV4" label="Deep Thinking">
            <el-switch v-model="llmStore.config.enable_reasoning" />
            <p class="help-text">
              Thinking is auto-disabled during tool calls to keep the agent chain stable.
            </p>
          </el-form-item>

          <template v-if="showDevOptions">
            <el-divider content-position="left">Developer Options</el-divider>

            <el-form-item label="Base URL">
              <el-input v-model="llmStore.config.base_url" placeholder="Leave empty for default endpoint" />
            </el-form-item>

            <div class="dev-actions">
              <el-button
                size="small"
                :loading="llmStore.isLoading"
                @click="refreshModels"
              >
                <el-icon><Refresh /></el-icon>
                Refresh Models
              </el-button>
              <el-button
                size="small"
                type="info"
                plain
                :loading="llmStore.isTesting"
                @click="runTest"
              >
                <el-icon><Aim /></el-icon>
                Test Connection
              </el-button>
            </div>

            <el-collapse v-model="advancedOpen" class="advanced-collapse">
              <el-collapse-item title="Advanced Sampling (ops/debug)" name="advanced">
                <div v-if="llmStore.paramControls.length > 0" class="advanced-params">
                  <template v-for="control in llmStore.paramControls" :key="control.param_name">
                    <template v-if="control.enabled">
                      <el-form-item
                        v-if="control.control_type === 'slider'"
                        :label="paramLabel(control)"
                        size="small"
                      >
                        <el-slider
                          :model-value="getConfigValue(control.param_name)"
                          @update:model-value="setConfigValue(control.param_name, $event)"
                          :min="control.min ?? 0"
                          :max="control.max ?? 2"
                          :step="control.step ?? 0.1"
                          :disabled="!!control.fixed"
                        />
                      </el-form-item>

                      <el-form-item
                        v-else-if="control.control_type === 'number'"
                        :label="paramLabel(control)"
                        size="small"
                      >
                        <el-input-number
                          :model-value="getConfigValue(control.param_name)"
                          @update:model-value="setConfigValue(control.param_name, $event)"
                          :min="control.min ?? 0"
                          :max="control.max ?? 100"
                          :step="control.step ?? 1"
                          style="width: 100%"
                          :disabled="!!control.fixed"
                        />
                      </el-form-item>

                      <el-form-item
                        v-else-if="control.control_type === 'select'"
                        :label="paramLabel(control)"
                        size="small"
                      >
                        <el-select
                          :model-value="getConfigValue(control.param_name)"
                          @update:model-value="setConfigValue(control.param_name, $event)"
                          style="width: 100%"
                        >
                          <el-option
                            v-for="choice in control.choices"
                            :key="choice"
                            :label="choice"
                            :value="choice"
                          />
                        </el-select>
                      </el-form-item>

                      <el-form-item
                        v-else-if="control.control_type === 'switch'"
                        :label="paramLabel(control)"
                        size="small"
                      >
                        <el-switch
                          :model-value="getConfigValue(control.param_name)"
                          @update:model-value="setConfigValue(control.param_name, $event)"
                        />
                      </el-form-item>
                    </template>
                  </template>
                </div>
                <p v-else-if="llmStore.isLoading" class="loading-hint">Loading capability table...</p>
                <p v-else class="loading-hint">Select a model to load capabilities</p>
              </el-collapse-item>
            </el-collapse>

            <el-alert
              v-if="llmStore.testResult"
              :type="llmStore.testResult.success ? 'success' : 'warning'"
              :title="llmStore.testResult.message"
              :closable="false"
              class="test-alert"
              size="small"
            />
          </template>

          <div class="form-actions">
            <el-button type="primary" @click="saveAndClose">Save</el-button>
          </div>
        </el-form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Setting, Close, Refresh, Aim } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useLLMStore, type LLMConfig } from '@/stores/llm'
import { useAuthStore } from '@/stores/auth'

const llmStore = useLLMStore()
const auth = useAuthStore()

defineEmits<{ close: [] }>()

/** 开发层：后端 DEBUG 或本地 vite dev */
const showDevOptions = computed(() => auth.debugMode || import.meta.env.DEV)
const advancedOpen = ref<string[]>([])

const modelsForProvider = computed(() =>
  llmStore.getModelsByProvider(llmStore.config.provider)
)

const selectedModelInfo = computed(() =>
  llmStore.availableModels.find(m => m.id === llmStore.config.model)
)

const isDeepSeekV4 = computed(
  () =>
    llmStore.config.provider === 'deepseek' &&
    llmStore.config.model.startsWith('deepseek-v4')
)

function mapPanelParamToConfigKey(paramName: string): keyof LLMConfig {
  if (paramName === 'web_search') return 'enable_online_search'
  return paramName as keyof LLMConfig
}

function getConfigValue(paramName: string): unknown {
  const key = mapPanelParamToConfigKey(paramName)
  return (llmStore.config as Record<string, unknown>)[key]
}

function setConfigValue(paramName: string, val: unknown): void {
  const key = mapPanelParamToConfigKey(paramName)
  ;(llmStore.config as Record<string, unknown>)[key] = val
}

const paramLabelsEn: Record<string, string> = {
  temperature: 'Temperature',
  top_p: 'Top P',
  top_k: 'Top K',
  max_tokens: 'Max Tokens',
  frequency_penalty: 'Frequency Penalty',
  presence_penalty: 'Presence Penalty',
  reasoning_effort: 'Reasoning Effort',
  web_search: 'Web Search',
  vision: 'Vision',
}

function paramLabel(control: { param_name: string; label_zh: string }): string {
  return paramLabelsEn[control.param_name] || control.label_zh
}

async function syncModelCapabilities() {
  await llmStore.fetchCapabilities(llmStore.config.provider, llmStore.config.model)
}

const onProviderChange = async () => {
  const models = modelsForProvider.value
  if (models.length > 0) {
    llmStore.config.model = models[0].id
  }
  await syncModelCapabilities()
  // 供应商/模型切换仅保存在浏览器本地（对话时随每条 WS 消息携带），
  // 不再即时 POST 服务端：全局槽是所有用户共享的，避免互相覆盖。
  llmStore.saveLocal()
}

const onModelChange = async () => {
  const model = selectedModelInfo.value
  if (model && llmStore.config.max_tokens > model.max_tokens) {
    llmStore.config.max_tokens = model.max_tokens
  }
  await syncModelCapabilities()
  llmStore.saveLocal()
}

const refreshModels = async () => {
  if (!llmStore.config.api_key) {
    ElMessage.warning('Please enter an API Key first')
    return
  }
  const ok = await llmStore.fetchLiveModels(
    llmStore.config.provider,
    llmStore.config.api_key,
    llmStore.config.base_url || undefined
  )
  if (ok) {
    ElMessage.success('Model list refreshed')
    const models = modelsForProvider.value
    if (models.length > 0 && !models.find(m => m.id === llmStore.config.model)) {
      llmStore.config.model = models[0].id
      await syncModelCapabilities()
    }
  } else {
    ElMessage.error('Refresh failed')
  }
}

const runTest = async () => {
  if (!llmStore.config.api_key) {
    ElMessage.warning('Please enter an API Key first')
    return
  }
  await llmStore.testConnection()
  if (llmStore.testResult) {
    ElMessage[llmStore.testResult.success ? 'success' : 'warning'](llmStore.testResult.message)
  }
}

const saveAndClose = async () => {
  const result = await llmStore.saveConfigToServer()
  if (result?.success) {
    llmStore.saveLocal()
    ElMessage.success('Saved')
    llmStore.showConfigPanel = false
  } else {
    ElMessage.error(result?.message || 'Save failed')
  }
}

onMounted(async () => {
  if (!auth.configLoaded) {
    await auth.fetchPublicConfig()
  }
  await llmStore.hydrateActiveConfigFromServer()
  await llmStore.fetchModels()
  await syncModelCapabilities()
})
</script>

<style scoped>
.llm-config-panel-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.llm-config-panel {
  width: 480px;
  max-height: 90vh;
  background: rgba(15, 23, 42, 0.98);
  border: 1px solid rgba(13, 148, 136, 0.2);
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-bottom: 1px solid rgba(13, 148, 136, 0.15);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #e2e8f0;
}

.panel-title .el-icon {
  color: #14b8a6;
}

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px 22px;
}

.model-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.model-description,
.help-text {
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}

.dev-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.advanced-collapse {
  margin-bottom: 12px;
  border: none;
}

.advanced-params {
  padding-top: 4px;
}

.loading-hint {
  text-align: center;
  padding: 12px;
  color: #64748b;
  font-size: 13px;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.test-alert {
  margin-bottom: 12px;
}

:deep(.el-form-item__label) {
  color: #94a3b8;
  font-weight: 500;
}

:deep(.el-input__wrapper) {
  background: rgba(30, 41, 59, 0.6);
  box-shadow: none;
}

:deep(.el-collapse-item__header) {
  background: transparent;
  color: #94a3b8;
  font-size: 13px;
  border-bottom-color: rgba(30, 58, 95, 0.4);
}

:deep(.el-collapse-item__wrap) {
  background: transparent;
  border-bottom: none;
}
</style>
