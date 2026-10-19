import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

export interface ToolCallInfo {
  tool_name: string
  arguments: Record<string, any>
  result?: any
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  isStreaming?: boolean
  toolCalls?: ToolCallInfo[]
  state?: 'thinking' | 'tool_calling' | 'idle' | 'error'
}

const MESSAGES_STORAGE_PREFIX = 'agent_framework_messages_'

function getStorageKey(sessionId: string): string {
  return `${MESSAGES_STORAGE_PREFIX}${sessionId}`
}

export const useChatStore = defineStore('chat', () => {
  const sessionId = ref<string>('')
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const streamingMessageId = ref<string | null>(null)

  let saveTimer: ReturnType<typeof setTimeout> | null = null
  let streamingTimeout: ReturnType<typeof setTimeout> | null = null
  const STREAMING_TIMEOUT_MS = 120000

  function clearStreamingTimeout() {
    if (streamingTimeout) {
      clearTimeout(streamingTimeout)
      streamingTimeout = null
    }
  }

  function resetStreamingTimeout() {
    clearStreamingTimeout()
    streamingTimeout = setTimeout(() => {
      if (streamingMessageId.value) {
        console.warn('[ChatStore] 流式消息超时，自动终止')
        const msg = messages.value.find(m => m.id === streamingMessageId.value)
        if (msg) {
          msg.isStreaming = false
          msg.state = 'error'
          if (!msg.content) {
            msg.content = 'Response timed out. Please retry.'
          }
        }
        streamingMessageId.value = null
        saveMessages()
      }
    }, STREAMING_TIMEOUT_MS)
  }

  function touchStreamingTimeout() {
    if (streamingMessageId.value) {
      resetStreamingTimeout()
    }
  }

  function loadMessagesForSession(targetSessionId: string): ChatMessage[] {
    if (!targetSessionId) return []
    try {
      const stored = localStorage.getItem(getStorageKey(targetSessionId))
      if (stored) {
        return JSON.parse(stored)
      }
    } catch (e) {
      console.error('Failed to load messages from storage:', e)
    }
    return []
  }

  function saveMessages() {
    if (!sessionId.value) return
    try {
      const messagesToSave = messages.value.filter(m => !m.isStreaming)
      localStorage.setItem(getStorageKey(sessionId.value), JSON.stringify(messagesToSave))
    } catch (e) {
      console.error('Failed to save messages to storage:', e)
    }
  }

  function debouncedSaveMessages() {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => {
      saveMessages()
      saveTimer = null
    }, 500)
  }

  function switchSession(newSessionId: string) {
    if (sessionId.value && messages.value.length > 0) {
      saveMessages()
    }
    clearStreamingTimeout()
    sessionId.value = newSessionId
    messages.value = loadMessagesForSession(newSessionId)
    streamingMessageId.value = null
  }

  watch(messages, debouncedSaveMessages, { deep: true })

  const messageCount = computed(() => messages.value.length)
  const lastMessage = computed(() => messages.value[messages.value.length - 1])
  const isStreaming = computed(() => !!streamingMessageId.value)

  const setSessionId = (id: string) => {
    sessionId.value = id
  }

  const addMessage = (message: Omit<ChatMessage, 'id' | 'timestamp'>) => {
    const newMessage: ChatMessage = {
      ...message,
      id: `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      timestamp: new Date().toISOString()
    }
    messages.value.push(newMessage)
    return newMessage.id
  }

  const startStreamingMessage = (state: 'thinking' | 'tool_calling' = 'thinking') => {
    const id = `msg_stream_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
    const msg: ChatMessage = {
      id,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      isStreaming: true,
      state,
      toolCalls: []
    }
    messages.value.push(msg)
    streamingMessageId.value = id
    resetStreamingTimeout()
    return id
  }

  const appendToken = (token: string) => {
    if (!streamingMessageId.value) return
    const msg = messages.value.find(m => m.id === streamingMessageId.value)
    if (msg) {
      msg.content += token
      resetStreamingTimeout()
    }
  }

  const addToolCall = (toolCall: ToolCallInfo) => {
    if (!streamingMessageId.value) return
    const msg = messages.value.find(m => m.id === streamingMessageId.value)
    if (msg) {
      msg.toolCalls = msg.toolCalls || []
      msg.toolCalls.push(toolCall)
      msg.state = 'tool_calling'
      resetStreamingTimeout()
    }
  }

  const addToolResult = (toolName: string, result: any) => {
    if (!streamingMessageId.value) return
    const msg = messages.value.find(m => m.id === streamingMessageId.value)
    if (msg && msg.toolCalls) {
      const tc = msg.toolCalls.find(t => t.tool_name === toolName && t.result === undefined)
      if (tc) {
        tc.result = result
      }
    }
  }

  const finishStreaming = (finalContent?: string, state: 'idle' | 'error' = 'idle') => {
    if (!streamingMessageId.value) return
    clearStreamingTimeout()
    const msg = messages.value.find(m => m.id === streamingMessageId.value)
    if (msg) {
      msg.isStreaming = false
      msg.state = state
      if (finalContent) {
        msg.content = finalContent
      }
    }
    streamingMessageId.value = null
    saveMessages()
  }

  const clearMessages = () => {
    messages.value = []
    streamingMessageId.value = null
    clearStreamingTimeout()
  }

  const setLoading = (loading: boolean) => {
    isLoading.value = loading
  }

  const deleteMessage = (messageId: string) => {
    const index = messages.value.findIndex(m => m.id === messageId)
    if (index !== -1) {
      messages.value.splice(index, 1)
    }
  }

  const deleteMessagesAfter = (messageId: string) => {
    const index = messages.value.findIndex(m => m.id === messageId)
    if (index !== -1) {
      messages.value = messages.value.slice(0, index)
    }
  }

  const updateMessage = (messageId: string, updates: Partial<ChatMessage>) => {
    const msg = messages.value.find(m => m.id === messageId)
    if (msg) {
      Object.assign(msg, updates)
    }
  }

  return {
    sessionId,
    messages,
    isLoading,
    streamingMessageId,
    isStreaming,
    messageCount,
    lastMessage,
    setSessionId,
    addMessage,
    startStreamingMessage,
    appendToken,
    addToolCall,
    addToolResult,
    finishStreaming,
    touchStreamingTimeout,
    clearMessages,
    setLoading,
    deleteMessage,
    deleteMessagesAfter,
    updateMessage,
    switchSession,
    loadMessagesForSession
  }
})
