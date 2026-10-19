<template>
  <div class="login-view">
    <div class="login-card">
      <div class="login-header">
        <h2 class="login-title">进入 ChickenSV-Agent</h2>
        <p class="login-subtitle">公网模式下，请选择你想使用的模型来源</p>
      </div>

      <el-tabs v-model="mode" class="login-tabs">
        <el-tab-pane label="使用平台默认模型" name="default" :disabled="!auth.hasDefaultModel">
          <div class="mode-desc">
            <p>无需配置，使用平台提供的免费模型。</p>
            <p v-if="platformLimitHint" class="hint">{{ platformLimitHint }}</p>
            <p v-else class="hint">为防止滥用，平台免费模型有调用频次限制；BYOK 不受限。</p>
          </div>
          <el-button
            type="primary"
            class="enter-btn"
            :disabled="!auth.hasDefaultModel"
            @click="enterWithDefault"
          >
            <el-icon><ChatDotRound /></el-icon>
            进入对话
          </el-button>
        </el-tab-pane>

        <el-tab-pane label="使用我自己的 API Key (BYOK)" name="byok">
          <div class="mode-desc">
            <p>你的 Key 仅保存在当前浏览器标签页（sessionStorage），</p>
            <p>关闭标签页即清除，<strong>绝不上传到后端持久化</strong>。</p>
          </div>

          <el-form label-position="top" @submit.prevent="enterWithByok">
            <el-form-item label="供应商">
              <el-radio-group v-model="provider">
                <el-radio-button value="qwen">通义千问</el-radio-button>
                <el-radio-button value="deepseek">DeepSeek</el-radio-button>
                <el-radio-button value="openrouter">OpenRouter</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="API Key">
              <el-input
                v-model="apiKey"
                type="password"
                show-password
                placeholder="sk-..."
                clearable
              />
            </el-form-item>

            <el-button
              type="primary"
              class="enter-btn"
              :disabled="!apiKey.trim()"
              @click="enterWithByok"
            >
              <el-icon><Key /></el-icon>
              保存到本会话并进入
            </el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <div class="security-tips">
        <el-icon><Lock /></el-icon>
        <span>不同浏览器标签页之间的 Key 相互隔离，互不可见。</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ChatDotRound, Key, Lock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useLLMStore, type LLMProvider } from '@/stores/llm'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const llmStore = useLLMStore()

const mode = ref<'default' | 'byok'>('default')
const provider = ref<LLMProvider>('deepseek')
const apiKey = ref('')

const platformLimitHint = computed(() => {
  const parts: string[] = []
  if (auth.burstLimit && auth.burstWindowSeconds) {
    const mins = Math.max(1, Math.round(auth.burstWindowSeconds / 60))
    parts.push(`${mins} 分钟内最多 ${auth.burstLimit} 次`)
  }
  if (auth.dailyQuota) parts.push(`每日最多 ${auth.dailyQuota} 次`)
  return parts.length ? `免费额度：${parts.join('，')}（仅平台 Key；BYOK 不限）` : ''
})

onMounted(() => {
  auth.fetchPublicConfig()
  auth.fetchQuota()
})

function redirectToChat() {
  const target = (route.query.redirect as string) || '/chat'
  router.replace(target)
}

function enterWithDefault() {
  auth.setSession('default-' + Date.now())
  ElMessage.success('已进入默认模型模式')
  redirectToChat()
}

function enterWithByok() {
  const k = apiKey.value.trim()
  if (!k) {
    ElMessage.warning('请填写 API Key')
    return
  }
  llmStore.config.provider = provider.value
  llmStore.setApiKeyForProvider(provider.value, k)
  auth.setSession('byok-' + Date.now())
  ElMessage.success('Key 已保存到当前会话（仅本标签页）')
  redirectToChat()
}
</script>

<style scoped>
.login-view {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #f0fdfa 0%, #ecfeff 100%);
  padding: 24px;
}

.login-card {
  width: 100%;
  max-width: 480px;
  background: #ffffff;
  border-radius: 18px;
  padding: 36px 32px;
  box-shadow: 0 12px 40px rgba(13, 148, 136, 0.12);
  border: 1px solid rgba(13, 148, 136, 0.12);
}

.login-header {
  text-align: center;
  margin-bottom: 24px;
}

.login-title {
  margin: 0 0 8px;
  font-size: 22px;
  color: #0f172a;
}

.login-subtitle {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.login-tabs {
  margin-top: 8px;
}

.mode-desc {
  margin: 8px 0 16px;
  color: #475569;
  font-size: 13px;
  line-height: 1.7;
}

.mode-desc .hint {
  color: #94a3b8;
  margin: 0;
}

.enter-btn {
  width: 100%;
  height: 44px;
  font-size: 15px;
  border-radius: 22px;
  background: linear-gradient(135deg, #0d9488 0%, #06b6d4 100%);
  border: none;
}

.security-tips {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px dashed rgba(148, 163, 184, 0.3);
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 12px;
}
</style>
