<template>
  <div class="chat-view">
    <!-- 左侧边栏 - 对话列表 -->
    <SessionSidebar 
      :sessions="sessionStore.sessions"
      :current-session-id="sessionStore.currentSessionId"
      @create="createNewSession"
      @switch="switchToSession"
      @delete="deleteSession"
    />
    
    <!-- 主内容区 -->
    <div class="chat-main">
      <!-- 顶部导航 -->
      <div class="chat-header">
        <div class="header-left">
          <h2 class="session-title">
            {{ sessionStore.currentSession?.title || 'New Chat' }}
            <el-button text @click="editSessionTitle">
              <el-icon><Edit /></el-icon>
            </el-button>
          </h2>
        </div>
        <div class="header-right">
          <el-button 
            class="llm-config-btn" 
            @click="llmStore.toggleConfigPanel"
          >
            <el-icon><Setting /></el-icon>
            Model Settings
          </el-button>
          
          <el-dropdown @command="handleWorkspaceCommand">
            <el-button class="workspace-btn">
              <el-icon><Plus /></el-icon>
              Workspace
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="query">
                  <el-icon><Search /></el-icon>
                  Data Query
                </el-dropdown-item>
                <el-dropdown-item command="imputation">
                  <el-icon><DataAnalysis /></el-icon>
                  Imputation
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          
          <el-tag :type="connectionStatus.type" size="small">
            <el-icon v-if="connectionStatus.connected"><CircleCheck /></el-icon>
            <el-icon v-else><CircleClose /></el-icon>
            {{ connectionStatus.text }}
          </el-tag>
        </div>
      </div>
      
      <!-- 对话内容区 -->
      <div class="chat-content">
        <ChatWindow 
          :messages="messages" 
          :loading="loading"
          @send="handleSend"
          @retry="handleRetry"
          @edit="handleEdit"
        />
      </div>
    </div>
    
    <!-- 右侧工作区面板 -->
    <transition name="workspace-slide">
      <WorkspacePanel 
        v-if="sessionStore.hasWorkspace"
        :workspace-id="sessionStore.currentWorkspaceId"
        :workspace-type="sessionStore.workspaceType"
        :workspace-action="sessionStore.workspaceAction"
        @close="() => {}"
      />
    </transition>
    
    <!-- LLM配置面板 -->
    <LLMConfigPanel 
      v-if="llmStore.showConfigPanel"
      @close="llmStore.toggleConfigPanel"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { 
  Edit, Setting, Plus, Search, DataAnalysis, 
  CircleCheck, CircleClose 
} from '@element-plus/icons-vue'
import axios from 'axios'

import SessionSidebar from '@/components/chat/SessionSidebar.vue'
import ChatWindow from '@/components/chat/ChatWindow.vue'
import WorkspacePanel from '@/components/workspace/WorkspacePanel.vue'
import LLMConfigPanel from '@/components/llm/LLMConfigPanel.vue'

import { useChatStore } from '@/stores/chat'
import { useSessionStore } from '@/stores/session'
import { useLLMStore } from '@/stores/llm'
import { WebSocketClient } from '@/websocket/client'

const chatStore = useChatStore()
const sessionStore = useSessionStore()
const llmStore = useLLMStore()

const wsClient = ref<WebSocketClient | null>(null)

const messages = computed(() => chatStore.messages)
const loading = computed(() => chatStore.isStreaming)
const connectionStatus = computed(() => {
  if (wsClient.value?.isConnected) {
    return { connected: true, type: 'success' as const, text: 'Connected' }
  }
  return { connected: false, type: 'danger' as const, text: 'Disconnected' }
})

const createNewSession = () => {
  const sessionId = sessionStore.createSession('New Chat')
  chatStore.switchSession(sessionId)

  wsClient.value?.disconnect()
  wsClient.value = new WebSocketClient(sessionId)
  setupWebSocketHandlers()
  wsClient.value.connect()
}

const switchToSession = async (targetSessionId: string) => {
  sessionStore.switchSession(targetSessionId)
  chatStore.switchSession(targetSessionId)
  await hydrateWorkspaceForSession(targetSessionId)

  wsClient.value?.disconnect()
  wsClient.value = new WebSocketClient(targetSessionId)
  setupWebSocketHandlers()
  wsClient.value.connect()
}

const deleteSession = (sessionId: string) => {
  sessionStore.deleteSession(sessionId)
  if (sessionStore.sessions.length === 0) {
    createNewSession()
  }
}

const editSessionTitle = async () => {
  if (!sessionStore.currentSession) return
  
  try {
    const { value } = await ElMessageBox.prompt(
      'Enter a new conversation title',
      'Rename Conversation',
      {
        confirmButtonText: 'OK',
        cancelButtonText: 'Cancel',
        inputValue: sessionStore.currentSession.title
      }
    )
    if (value) {
      sessionStore.updateSessionTitle(sessionStore.currentSessionId, value)
    }
  } catch {
    // 用户取消
  }
}

const handleWorkspaceCommand = (command: string) => {
  switch (command) {
    case 'query':
      createWorkspace('query')
      break
    case 'imputation':
      createWorkspace('imputation')
      break
  }
}

const hydrateWorkspaceForSession = async (sessionId: string) => {
  if (!sessionId) return
  sessionStore.applySessionWorkspace(sessionId)
  if (sessionStore.hasWorkspace) return

  try {
    const resp = await axios.get(`/api/v1/workspaces/by-session/${encodeURIComponent(sessionId)}`)
    const data = resp.data || {}
    if (data.workspace_id) {
      sessionStore.setWorkspace(data.workspace_id, data.workspace_type || 'imputation')
    }
  } catch {
    // 无绑定工作区
  }
}

const createWorkspace = async (type: 'query' | 'imputation') => {
  const sessionId = sessionStore.currentSessionId
  if (!sessionId) {
    ElMessage.warning('Please create or select a conversation first')
    return
  }

  if (sessionStore.hasWorkspace) {
    ElMessage.info('This conversation already has a workspace (one per conversation)')
    return
  }

  try {
    const resp = await axios.post('/api/v1/workspaces', {
      workspace_type: type,
      session_id: sessionId,
      description: `${type === 'query' ? 'Data Query' : 'Imputation'} workspace`,
    })
    const { workspace_id } = resp.data
    sessionStore.setWorkspace(workspace_id, type)
    ElMessage.success(
      resp.data.status === 'existing'
        ? 'Restored workspace for this conversation'
        : `${type === 'query' ? 'Data Query' : 'Imputation'} workspace created`
    )
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || 'Failed to create workspace')
  }
}

const buildLLMConfig = () => ({
  provider: llmStore.config.provider,
  model: llmStore.config.model,
  api_key: llmStore.config.api_key,
  base_url: llmStore.config.base_url || undefined,
  temperature: llmStore.config.temperature,
  max_tokens: llmStore.config.max_tokens,
  top_p: llmStore.config.top_p,
  frequency_penalty: llmStore.config.frequency_penalty,
  presence_penalty: llmStore.config.presence_penalty,
  enable_online_search: llmStore.config.enable_online_search,
  enable_reasoning: llmStore.config.enable_reasoning,
  top_k: llmStore.config.top_k ?? undefined,
  reasoning_effort: llmStore.config.reasoning_effort ?? undefined
})


const requestRoundCancel = () => {
  if (wsClient.value?.isConnected) {
    wsClient.value.send({
      type: 'cancel',
      payload: { reason: 'new_request' }
    })
  }
  chatStore.finishStreaming(undefined, 'error')
}

const sendChatMessage = (content: string) => {
  if (!wsClient.value) {
    chatStore.addMessage({
      role: 'assistant',
      content: 'Connection not ready. Please try again shortly.',
      state: 'error'
    })
    return
  }

  requestRoundCancel()

  const isConnected = wsClient.value.isConnected
  if (isConnected) {
    chatStore.startStreamingMessage('thinking')
  }

  wsClient.value.send({
    type: 'chat',
    payload: { content, llm_config: buildLLMConfig() }
  })

  if (!isConnected) {
    ElMessage.info('Connection not ready. Message queued and will send when connected.')
  }
}

const handleSend = async (content: string) => {
  if (!content.trim()) return

  chatStore.addMessage({
    role: 'user',
    content
  })

  sessionStore.incrementMessageCount(sessionStore.currentSessionId)

  try {
    sendChatMessage(content)
  } catch (error) {
    console.error('发送消息失败:', error)
    chatStore.finishStreaming(undefined, 'error')
    chatStore.addMessage({
      role: 'assistant',
      content: 'Failed to send message. Please try again.',
      state: 'error'
    })
  }
}

const handleRetry = async (message: any) => {
  const msgIndex = chatStore.messages.findIndex(m => m.id === message.id)
  if (msgIndex <= 0) return

  const userMessage = chatStore.messages[msgIndex - 1]
  if (userMessage.role !== 'user') return

  chatStore.deleteMessage(message.id)

  try {
    sendChatMessage(userMessage.content)
  } catch (error) {
    console.error('重试失败:', error)
    chatStore.addMessage({
      role: 'assistant',
      content: 'Retry failed. Please try again later.',
      state: 'error'
    })
  }
}

const editingMessageId = ref<string | null>(null)
const editInputContent = ref('')

const handleEdit = async (message: any) => {
  // 设置编辑状态
  editingMessageId.value = message.id
  editInputContent.value = message.content

  // 找到对应的 ChatWindow 组件并设置输入值
  // 通过事件总线或直接操作 DOM 的方式将内容填充到输入框
  const chatWindow = document.querySelector('.chat-window textarea') as HTMLTextAreaElement
  if (chatWindow) {
    chatWindow.value = message.content
    chatWindow.focus()

    // 保存原始发送函数
    // const originalSend = handleSend

    // 临时覆盖发送处理
    const handleEditSend = async (content: string) => {
      if (!content.trim()) return

      const msgIndex = chatStore.messages.findIndex(m => m.id === message.id)
      if (msgIndex === -1) return

      chatStore.deleteMessagesAfter(message.id)
      chatStore.updateMessage(message.id, { content })

      editingMessageId.value = null
      editInputContent.value = ''

      if (chatWindow) {
        chatWindow.value = ''
      }

      sessionStore.incrementMessageCount(sessionStore.currentSessionId)
      try {
        sendChatMessage(content)
      } catch (error) {
        console.error('发送消息失败:', error)
        chatStore.addMessage({
          role: 'assistant',
          content: 'Failed to send message. Please try again.',
          state: 'error'
        })
      }
    }

    // 通过自定义事件通知 ChatWindow 使用编辑模式
    window.dispatchEvent(new CustomEvent('message-edit-mode', {
      detail: {
        content: message.content,
        onSend: handleEditSend
      }
    }))
  }
}

const setupWebSocketHandlers = () => {
  if (!wsClient.value) return

  const finalizeStreamingOnConnectionIssue = (fallbackMessage: string) => {
    if (!chatStore.isStreaming) return
    const streamingMsg = chatStore.messages.find(m => m.isStreaming)
    if (streamingMsg) {
      streamingMsg.isStreaming = false
      streamingMsg.state = 'error'
      if (!streamingMsg.content) {
        streamingMsg.content = fallbackMessage
      }
    }
    chatStore.finishStreaming(undefined, 'error')
  }

  wsClient.value.onDisconnect = () => {
    finalizeStreamingOnConnectionIssue('Connection lost. Please retry.')
  }

  wsClient.value.onError = () => {
    finalizeStreamingOnConnectionIssue('Connection error. Please retry.')
  }
  
  wsClient.value.onMessage = (message) => {
    const msgType = message.type
    const payload = message.payload || {}

    switch (msgType) {
      case 'connected':
        console.log('[ChatView] WebSocket已连接:', payload.session_id)
        if (chatStore.isStreaming) {
          const staleMsg = chatStore.messages.find(m => m.isStreaming)
          if (staleMsg) {
            staleMsg.isStreaming = false
            staleMsg.state = 'error'
            if (!staleMsg.content) {
              staleMsg.content = 'Connection interrupted. Please retry.'
            }
          }
          chatStore.finishStreaming(undefined, 'error')
        }
        break

      case 'message_start':
        if (!chatStore.isStreaming) {
          chatStore.startStreamingMessage(payload.state || 'thinking')
        } else {
          const streamingMsg = chatStore.messages.find(m => m.isStreaming)
          if (streamingMsg && payload.state) {
            streamingMsg.state = payload.state
          }
        }
        break

      case 'token':
        chatStore.appendToken(payload.content || '')
        break

      case 'tool_call':
        chatStore.addToolCall({
          tool_name: payload.tool_name || '',
          arguments: payload.arguments || {}
        })
        break

      case 'tool_result':
        chatStore.addToolResult(payload.tool_name || '', payload.result)
        break

      case 'message_end':
        chatStore.finishStreaming(payload.content, payload.state || 'idle')
        break

      case 'pong':
        chatStore.touchStreamingTimeout()
        break

      case 'message':
        chatStore.addMessage({
          role: payload.role || 'assistant',
          content: payload.content,
          state: payload.state
        })
        break

      case 'workspace_activate': {
        const targetSession = payload.session_id
        if (targetSession && targetSession !== sessionStore.currentSessionId) {
          break
        }
        sessionStore.setWorkspace(
          payload.workspace_id,
          payload.workspace_type,
          payload.action
        )
        ElMessage({
          message: payload.reused
            ? 'Restored workspace for this conversation'
            : `${payload.workspace_type === 'imputation' ? 'Imputation' : 'Data Query'} workspace activated`,
          type: 'success',
          duration: 3000,
          showClose: true,
        })
        break
      }

      case 'auto_title':
        sessionStore.updateSessionTitle(sessionStore.currentSessionId, payload.title)
        break

      case 'error':
        ElMessage.error(payload.message || 'An error occurred')
        if (chatStore.isStreaming) {
          const streamingMsg = chatStore.messages.find(m => m.isStreaming)
          if (streamingMsg && !streamingMsg.content) {
            streamingMsg.content = payload.message || 'Processing failed. Please retry.'
          }
          chatStore.finishStreaming(undefined, 'error')
        }
        break

      default:
        console.log('[ChatView] 未处理的消息类型:', msgType)
    }
  }
}

onMounted(async () => {
  await llmStore.hydrateActiveConfigFromServer()
  await llmStore.syncConfigFromServer()

  // 如果没有会话，创建一个
  if (sessionStore.sessions.length === 0) {
    const newSessionId = sessionStore.createSession('New Chat')
    chatStore.switchSession(newSessionId)
  } else if (sessionStore.currentSessionId) {
    // 有当前会话，加载对应的消息
    chatStore.switchSession(sessionStore.currentSessionId)
  } else {
    // 有会话但没有当前会话，使用第一个
    const firstSessionId = sessionStore.sessions[0].id
    sessionStore.switchSession(firstSessionId)
    chatStore.switchSession(firstSessionId)
  }

  const sessionId = chatStore.sessionId || sessionStore.createSession('New Chat')
  if (!chatStore.sessionId) {
    chatStore.switchSession(sessionId)
  }
  sessionStore.applySessionWorkspace(sessionId)

  wsClient.value = new WebSocketClient(sessionId)
  setupWebSocketHandlers()
  wsClient.value.connect()
  await hydrateWorkspaceForSession(sessionId)
})

onUnmounted(() => {
  wsClient.value?.disconnect()
})
</script>

<style scoped>
.chat-view {
  height: 100vh;
  min-height: 100vh;
  display: flex;
  background: linear-gradient(135deg, #f8fffe 0%, #ffffff 45%, #f0fdfa 100%);
  overflow: hidden;
  position: relative;
  color: #374151;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100vh;
  background: #ffffff;
  overflow: hidden;
}

.chat-header {
  height: 64px;
  flex-shrink: 0;
  background: linear-gradient(135deg, #17afa3 0%, #12a3bd 100%);
  border-bottom: 1px solid rgba(13, 148, 136, 0.38);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  box-shadow: 0 8px 20px rgba(13, 148, 136, 0.32);
}

.header-left {
  display: flex;
  align-items: center;
}

.session-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #f8faff;
}

.session-title :deep(.el-button) {
  color: rgba(248, 250, 255, 0.9);
}

.session-title :deep(.el-button:hover) {
  color: #ffffff;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-right :deep(.el-button) {
  --el-button-bg-color: rgba(255, 255, 255, 0.16);
  --el-button-border-color: rgba(255, 255, 255, 0.38);
  --el-button-text-color: #f8faff;
  --el-button-hover-bg-color: rgba(255, 255, 255, 0.24);
  --el-button-hover-border-color: rgba(255, 255, 255, 0.58);
  --el-button-hover-text-color: #ffffff;
}

.workspace-btn {
  color: #f8faff;
}

.header-right :deep(.el-tag) {
  border-color: rgba(255, 255, 255, 0.45);
  background: rgba(255, 255, 255, 0.14);
  color: #ffffff;
}

.header-right :deep(.el-button--primary) {
  --el-button-bg-color: linear-gradient(135deg, #0D9488, #06B6D4);
  --el-button-border-color: #0D9488;
  --el-button-text-color: #fff;
}

.llm-config-btn {
  display: flex;
  align-items: center;
  gap: 6px;
}

.chat-content {
  flex: 1;
  padding: 20px;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  background: #ffffff;
}

.workspace-slide-enter-active {
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

.workspace-slide-leave-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.workspace-slide-enter-from {
  transform: translateX(100%);
  opacity: 0;
}

.workspace-slide-leave-to {
  transform: translateX(100%);
  opacity: 0;
}
</style>
