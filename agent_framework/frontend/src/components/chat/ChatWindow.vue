<template>
  <div class="chat-window">
    <div ref="messageListRef" class="message-list">
      <div
        v-for="message in messages"
        :key="message.id"
        class="message-item"
        :class="message.role"
      >
        <div class="message-avatar">
          <el-avatar :size="40" :class="message.role">
            <el-icon v-if="message.role === 'user'"><UserFilled /></el-icon>
            <el-icon v-else><Service /></el-icon>
          </el-avatar>
        </div>
        <div class="message-content">
          <!-- 工具调用状态显示 -->
          <div v-if="message.toolCalls && message.toolCalls.length > 0" class="tool-calls-section">
            <div class="tool-calls-header" @click="toggleToolCalls(message.id)">
              <el-icon class="toggle-icon" :class="{ expanded: expandedToolCalls.has(message.id) }">
                <ArrowRight />
              </el-icon>
              <span class="tool-calls-title">
                <el-icon><Tools /></el-icon>
                Tool Calls ({{ message.toolCalls.length }})
              </span>
            </div>
            <div v-show="expandedToolCalls.has(message.id)" class="tool-calls-content">
              <div v-for="(tc, idx) in message.toolCalls" :key="idx" class="tool-call-item">
                <div class="tool-call-header" @click="toggleToolResult(message.id, idx)">
                  <el-tag type="warning" size="small" effect="dark">
                    <el-icon><Tools /></el-icon>
                    {{ tc.tool_name }}
                  </el-tag>
                  <span class="tool-args">{{ formatToolArgs(tc.arguments) }}</span>
                  <el-icon v-if="tc.result !== undefined" class="toggle-icon result-toggle" :class="{ expanded: expandedResults.has(`${message.id}-${idx}`) }">
                    <ArrowRight />
                  </el-icon>
                </div>
                <div v-if="tc.result !== undefined && expandedResults.has(`${message.id}-${idx}`)" class="tool-result-content">
                  <div class="tool-result-label">Result</div>
                  <pre class="tool-result-json">{{ formatToolResult(tc.result) }}</pre>
                </div>
              </div>
            </div>
          </div>

          <!-- 流式工具调用状态 -->
          <div v-if="message.isStreaming && message.state === 'tool_calling'" class="tool-calling-state">
            <div class="tool-calling-indicator">
              <el-icon class="calling-icon"><Loading /></el-icon>
              <span>Calling tools</span>
              <span v-if="message.toolCalls && message.toolCalls.length > 0" class="calling-count">
                ({{ message.toolCalls.length }})
              </span>
            </div>
            <div v-if="message.toolCalls && message.toolCalls.length > 0" class="calling-tools-list">
              <el-tag
                v-for="(tc, idx) in message.toolCalls.slice(-3)"
                :key="idx"
                type="info"
                size="small"
                effect="plain"
              >
                {{ tc.tool_name }}
              </el-tag>
              <span v-if="message.toolCalls.length > 3" class="more-tools">+{{ message.toolCalls.length - 3 }}</span>
            </div>
          </div>

          <div v-if="message.isStreaming && !message.content" class="message-bubble thinking-state">
            <div class="thinking-indicator">
              <el-icon class="thinking-icon"><Loading /></el-icon>
              <span>{{ message.state === 'tool_calling' ? 'Calling tools...' : 'Thinking...' }}</span>
            </div>
          </div>

          <div v-if="message.content" class="message-bubble" :class="{ streaming: message.isStreaming, error: message.state === 'error' }">
            <div class="message-text" v-html="renderMarkdown(message.content)" />
            <span v-if="message.isStreaming" class="cursor-blink">|</span>
          </div>

          <div class="message-footer">
            <span class="message-time">{{ formatTime(message.timestamp) }}</span>
            <div v-if="!message.isStreaming" class="message-actions">
              <el-button
                v-if="message.role === 'assistant' && message.state === 'error'"
                text
                size="small"
                @click="$emit('retry', message)"
              >
                <el-icon><RefreshRight /></el-icon>
                Retry
              </el-button>
              <el-button
                v-if="message.role === 'user'"
                text
                size="small"
                @click="$emit('edit', message)"
              >
                <el-icon><Edit /></el-icon>
                Edit
              </el-button>
              <el-button
                v-if="message.role === 'assistant' && message.content"
                text
                size="small"
                @click="copyMessage(message.content)"
              >
                <el-icon><CopyDocument /></el-icon>
                Copy
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="loading && !hasStreamingMessage" class="message-item assistant">
        <div class="message-avatar">
          <el-avatar :size="40" class="assistant">
            <el-icon><Service /></el-icon>
          </el-avatar>
        </div>
        <div class="message-content">
          <div class="message-bubble typing">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
          </div>
        </div>
      </div>

      <div v-if="messages.length === 0 && !loading" class="empty-chat">
        <div class="empty-content">
          <el-icon class="empty-icon"><ChatDotRound /></el-icon>
          <h3>Start a new conversation</h3>
          <p>Type your question and I will help you explore chicken SV data</p>
          <div class="quick-actions">
            <el-button
              v-for="action in quickActions"
              :key="action.text"
              type="primary"
              plain
              size="small"
              @click="sendQuickAction(action.text)"
            >
              {{ action.text }}
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <div class="input-area">
      <div v-if="isEditMode" class="edit-mode-banner">
        <span class="edit-mode-text">
          <el-icon><Edit /></el-icon>
          Edit mode — press Enter to resend
        </span>
        <el-button text size="small" @click="cancelEditMode">
          <el-icon><Close /></el-icon>
          Cancel
        </el-button>
      </div>
      <div class="input-wrapper">
        <el-input
          v-model="inputMessage"
          type="textarea"
          :rows="3"
          :placeholder="isEditMode ? 'Edit message...' : 'Type a message... (Shift+Enter for new line)'"
          resize="none"
          @keydown.enter.prevent="handleEnter"
        />
        <div class="input-actions">
          <el-button
            v-if="isEditMode"
            text
            circle
            @click="cancelEditMode"
          >
            <el-icon><Close /></el-icon>
          </el-button>
          <el-button
            type="primary"
            circle
            :disabled="!inputMessage.trim() || loading"
            @click="sendMessage"
          >
            <el-icon><Promotion /></el-icon>
          </el-button>
        </div>
      </div>
      <div class="input-hint">
        <el-icon><InfoFilled /></el-icon>
        <span>{{ isEditMode ? 'Enter to resend, Esc to cancel' : 'Enter to send, Shift+Enter for new line' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import {
  UserFilled, Service, Promotion, ChatDotRound, InfoFilled,
  Tools, Loading, RefreshRight, Edit, CopyDocument, Close, ArrowRight
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { ChatMessage } from '@/stores/chat'

interface Props {
  messages: ChatMessage[]
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  loading: false
})

const emit = defineEmits<{
  send: [content: string]
  retry: [message: ChatMessage]
  edit: [message: ChatMessage]
}>()

const inputMessage = ref('')
const messageListRef = ref<HTMLDivElement>()
const isEditMode = ref(false)
const editHandler = ref<((content: string) => void) | null>(null)
const expandedToolCalls = ref<Set<string>>(new Set())
const expandedResults = ref<Set<string>>(new Set())

const toggleToolCalls = (messageId: string) => {
  if (expandedToolCalls.value.has(messageId)) {
    expandedToolCalls.value.delete(messageId)
  } else {
    expandedToolCalls.value.add(messageId)
  }
}

const toggleToolResult = (messageId: string, idx: number) => {
  const key = `${messageId}-${idx}`
  if (expandedResults.value.has(key)) {
    expandedResults.value.delete(key)
  } else {
    expandedResults.value.add(key)
  }
}

const quickActions = [
  { text: 'Query SV data' },
  { text: 'Genotype imputation' },
  { text: 'Analyze gene function' },
  { text: 'Database overview' }
]

const hasStreamingMessage = computed(() =>
  props.messages.some(m => m.isStreaming)
)

let scrollRafId = 0
const scheduleScrollToBottom = () => {
  if (!messageListRef.value) return
  if (scrollRafId) cancelAnimationFrame(scrollRafId)
  scrollRafId = requestAnimationFrame(() => {
    scrollRafId = 0
    const el = messageListRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

const escapeHtml = (text: string): string => {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

const renderMarkdown = (content: string): string => {
  let html = escapeHtml(content)

  // 代码块
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_match, lang, code) => {
    return `<pre class="code-block"><code class="language-${lang}">${code.trim()}</code></pre>`
  })

  // 表格支持 | 列1 | 列2 |
  html = html.replace(/\|([^\n]+)\|\n\|[-:\s|]+\|\n((?:\|[^\n]+\|\n?)+)/g, (_match, header, rows) => {
    const headers = header.split('|').map((h: string) => h.trim()).filter((h: string) => h)
    const rowData = rows.trim().split('\n').map((row: string) => {
      return row.split('|').map((c: string) => c.trim()).filter((c: string) => c)
    }).filter((row: string[]) => row.length > 0)
    
    let tableHtml = '<table class="markdown-table"><thead><tr>'
    headers.forEach((h: string) => {
      tableHtml += `<th>${h}</th>`
    })
    tableHtml += '</tr></thead><tbody>'
    
    rowData.forEach((row: string[]) => {
      tableHtml += '<tr>'
      row.forEach((cell: string) => {
        tableHtml += `<td>${cell}</td>`
      })
      tableHtml += '</tr>'
    })
    tableHtml += '</tbody></table>'

    return `<div class="md-table-wrap">${tableHtml}</div>`
  })

  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  html = html.replace(/\n/g, '<br>')

  return html
}

const formatToolArgs = (args: Record<string, any>): string => {
  const entries = Object.entries(args)
  if (entries.length === 0) return ''
  return entries.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')
}

const formatToolResult = (result: any): string => {
  if (result === null || result === undefined) return ''
  if (typeof result === 'string') {
    try {
      const parsed = JSON.parse(result)
      return JSON.stringify(parsed, null, 2)
    } catch {
      return result
    }
  }
  try {
    return JSON.stringify(result, null, 2)
  } catch {
    return String(result)
  }
}

const formatTime = (timestamp: string): string => {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit'
  })
}

const copyMessage = async (content: string) => {
  try {
    await navigator.clipboard.writeText(content)
    ElMessage.success('Copied to clipboard')
  } catch {
    ElMessage.error('Copy failed')
  }
}

const sendMessage = () => {
  const content = inputMessage.value.trim()
  if (!content || props.loading) return

  if (isEditMode.value && editHandler.value) {
    editHandler.value(content)
    cancelEditMode()
  } else {
    emit('send', content)
  }
  inputMessage.value = ''
}

const cancelEditMode = () => {
  isEditMode.value = false
  editHandler.value = null
  inputMessage.value = ''
}

const handleEditMode = (event: CustomEvent) => {
  isEditMode.value = true
  inputMessage.value = event.detail.content
  editHandler.value = event.detail.onSend
  nextTick(() => {
    const textarea = document.querySelector('.chat-window textarea') as HTMLTextAreaElement
    if (textarea) {
      textarea.focus()
      textarea.setSelectionRange(textarea.value.length, textarea.value.length)
    }
  })
}

onMounted(() => {
  window.addEventListener('message-edit-mode', handleEditMode as EventListener)
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('message-edit-mode', handleEditMode as EventListener)
  window.removeEventListener('keydown', handleKeydown)
})

const sendQuickAction = (text: string) => {
  emit('send', text)
}

const handleEnter = (e: KeyboardEvent) => {
  if (!e.shiftKey) {
    sendMessage()
  }
}

const handleKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && isEditMode.value) {
    cancelEditMode()
  }
}

watch(
  () => props.messages,
  () => {
    nextTick(scheduleScrollToBottom)
  },
  { deep: true }
)
</script>

<style scoped>
.chat-window {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  color: #374151;
  border-radius: 16px;
  border: 1px solid rgba(57, 146, 139, 0.2);
  box-shadow: 0 14px 30px rgba(44, 150, 141, 0.12);
  overflow: hidden;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  scroll-behavior: auto;
  background: #ffffff;
}

.message-item {
  display: flex;
  margin-bottom: 24px;
  gap: 12px;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.message-item.user {
  flex-direction: row-reverse;
}

.message-avatar .el-avatar {
  background: linear-gradient(135deg, #2db8ac 0%, #0eb8d6 100%);
  color: #ffffff;
}

.message-avatar .el-avatar.user {
  background: linear-gradient(135deg, #10B981 0%, #34D399 100%);
}

.message-content {
  max-width: 74%;
  min-width: 0;
}

.tool-calls-section {
  margin-bottom: 12px;
  background: rgba(13, 148, 136, 0.10);
  border: 1px solid rgba(13, 148, 136, 0.26);
  border-radius: 10px;
  overflow: hidden;
}

.tool-calls-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.tool-calls-header:hover {
  background: rgba(13, 148, 136, 0.14);
}

.toggle-icon {
  transition: transform 0.2s;
  color: #4B5563;
}

.toggle-icon.expanded {
  transform: rotate(90deg);
}

.tool-calls-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #0f766e;
  font-weight: 600;
}

.tool-calls-content {
  padding: 8px 12px 12px;
  border-top: 1px solid rgba(13, 148, 136, 0.18);
}

.tool-call-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 0;
  font-size: 12px;
}

.tool-call-item:not(:last-child) {
  border-bottom: 1px dashed rgba(13, 148, 136, 0.18);
}

.tool-call-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.tool-call-header:hover {
  background: rgba(13, 148, 136, 0.12);
  border-radius: 4px;
}

.result-toggle {
  margin-left: auto;
  font-size: 12px;
  color: #4B5563;
}

.tool-result-content {
  margin-top: 6px;
  padding: 10px;
  background: #f7fffd;
  border-radius: 8px;
  border: 1px solid rgba(13, 148, 136, 0.22);
  overflow-x: auto;
}

.tool-result-label {
  font-size: 11px;
  color: #0D9488;
  margin-bottom: 4px;
  font-weight: 600;
}

.tool-result-json {
  margin: 0;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
}

.tool-args {
  color: #4B5563;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-calling-state {
  margin-bottom: 12px;
  padding: 10px 14px;
  background: rgba(13, 148, 136, 0.06);
  border: 1px solid rgba(13, 148, 136, 0.2);
  border-radius: 10px;
}

.tool-calling-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #0D9488;
  font-size: 13px;
  font-weight: 500;
}

.calling-icon {
  animation: spin 1s linear infinite;
}

.calling-count {
  color: #0D9488;
  font-weight: normal;
}

.calling-tools-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
  padding-left: 24px;
}

.more-tools {
  font-size: 12px;
  color: #4B5563;
  padding: 2px 6px;
}

.thinking-state {
  display: flex;
  align-items: center;
}

.thinking-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #0D9488;
  font-size: 14px;
}

.thinking-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.message-bubble {
  padding: 14px 18px;
  border-radius: 18px;
  background: #f8fffe;
  color: #334155;
  word-break: break-word;
  line-height: 1.65;
  box-shadow: 0 8px 16px rgba(13, 148, 136, 0.12);
  border: 1px solid rgba(13, 148, 136, 0.24);
}

.message-bubble.streaming {
  border-bottom-right-radius: 4px;
}

.message-bubble.error {
  background: #FEF2F2;
  border: 1px solid rgba(239, 68, 68, 0.18);
  color: #B91C1C;
}

.message-item.user .message-bubble {
  background: linear-gradient(135deg, #0D9488 0%, #06B6D4 100%);
  color: #ffffff;
  border: none;
  box-shadow: 0 8px 16px rgba(13, 148, 136, 0.28);
}

.cursor-blink {
  animation: blink 1s step-end infinite;
  color: #0D9488;
  font-weight: bold;
}

@keyframes blink {
  50% { opacity: 0; }
}

.message-text :deep(.code-block) {
  background: #ffffff;
  color: #4B5563;
  padding: 12px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.5;
  border: 1px solid rgba(13, 148, 136, 0.15);
}

.message-text :deep(.inline-code) {
  background: rgba(13, 148, 136, 0.08);
  color: #0D9488;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 13px;
}

.message-item.user .message-text :deep(.inline-code) {
  background: rgba(255, 255, 255, 0.16);
  color: white;
}

.message-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
  padding: 0 8px;
}

.message-time {
  font-size: 12px;
  color: #475569;
}

.message-actions {
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.2s;
}

.message-item:hover .message-actions {
  opacity: 1;
}

.message-actions .el-button {
  color: #4B5563;
  font-size: 12px;
  padding: 2px 6px;
}

.message-actions .el-button:hover {
  color: #0D9488;
}

.message-item.user .message-footer {
  flex-direction: row-reverse;
}

.message-bubble.typing {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 18px 24px;
  min-width: 60px;
}

.typing-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #14B8A6;
  animation: typing 1.4s infinite;
}

.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-8px); opacity: 1; }
}

.empty-chat {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-content {
  text-align: center;
  padding: 40px;
}

.empty-icon {
  font-size: 64px;
  color: rgba(13, 148, 136, 0.2);
  margin-bottom: 20px;
}

.empty-content h3 {
  font-size: 20px;
  color: #374151;
  margin-bottom: 12px;
}

.empty-content p {
  color: #4B5563;
  margin-bottom: 24px;
}

.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: center;
}

.quick-actions :deep(.el-button) {
  --el-button-bg-color: rgba(13, 148, 136, 0.1);
  --el-button-border-color: rgba(13, 148, 136, 0.3);
  --el-button-text-color: #0D9488;
  --el-button-hover-bg-color: rgba(13, 148, 136, 0.2);
  --el-button-hover-border-color: rgba(13, 148, 136, 0.5);
  --el-button-hover-text-color: #0D9488;
}

.input-area {
  padding: 20px 24px;
  border-top: 1px solid rgba(13, 148, 136, 0.22);
  background: #ffffff;
}

.edit-mode-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  margin-bottom: 12px;
  background: rgba(13, 148, 136, 0.08);
  border: 1px solid rgba(13, 148, 136, 0.16);
  border-radius: 8px;
  color: #374151;
  font-size: 13px;
}

.edit-mode-text {
  display: flex;
  align-items: center;
  gap: 6px;
}

.edit-mode-banner .el-button {
  color: #0D9488;
}

.input-wrapper {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.input-wrapper .el-textarea { flex: 1; }

.input-wrapper .el-textarea :deep(.el-textarea__inner) {
  border-radius: 12px;
  padding: 12px 16px;
  resize: none;
  background: #ffffff;
  border: 1px solid rgba(13, 148, 136, 0.28);
  color: #334155;
  box-shadow: 0 3px 10px rgba(13, 148, 136, 0.08);
}

.input-wrapper .el-textarea :deep(.el-textarea__inner):focus {
  border-color: rgba(13, 148, 136, 0.65);
  box-shadow: 0 0 0 2px rgba(13, 148, 136, 0.14);
}

.input-wrapper .el-textarea :deep(.el-textarea__inner)::placeholder {
  color: #4B5563;
}

.input-actions .el-button {
  width: 44px;
  height: 44px;
  font-size: 18px;
}

.input-actions :deep(.el-button--primary) {
  background: linear-gradient(135deg, #0D9488, #06B6D4) !important;
  border: none !important;
}

.input-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 12px;
  color: #4B5563;
  padding-left: 8px;
}

.message-text {
  overflow-x: auto;
  overflow-y: visible;
}

.message-text :deep(.md-table-wrap) {
  display: block;
  overflow-x: auto;
  overflow-y: visible;
  max-width: 100%;
  margin: 12px 0;
  -webkit-overflow-scrolling: touch;
  contain: content;
}

:deep(.markdown-table) {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  margin: 0;
  font-size: 14px;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
}

:deep(.markdown-table thead) {
  background: linear-gradient(135deg, #0D9488 0%, #06B6D4 100%);
  color: #ffffff;
}

:deep(.markdown-table th) {
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
  border: none;
}

:deep(.markdown-table td) {
  padding: 10px 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  border-right: 1px solid rgba(148, 163, 184, 0.16);
  color: #4B5563;
}

:deep(.markdown-table td:last-child) {
  border-right: none;
}

:deep(.markdown-table tbody tr:hover) {
  background-color: rgba(13, 148, 136, 0.08);
}

:deep(.markdown-table tbody tr:nth-child(even)) {
  background-color: rgba(248, 250, 252, 0.85);
}

:deep(.markdown-table tbody tr:nth-child(even):hover) {
  background-color: rgba(13, 148, 136, 0.1);
}
</style>
