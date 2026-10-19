<template>
  <div class="session-sidebar">
    <div class="sidebar-header">
      <h3 class="logo">
        <svg class="logo-dna" width="24" height="24" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M8,2 C8,6 4,8 4,16 C4,24 8,26 8,30" stroke="#14B8A6" stroke-width="2.5" stroke-linecap="round"/>
          <path d="M24,2 C24,6 28,8 28,16 C28,24 24,26 24,30" stroke="#06B6D4" stroke-width="2.5" stroke-linecap="round"/>
          <line x1="10" y1="6" x2="22" y2="6" stroke="#5EEAD4" stroke-width="1.5" opacity="0.5"/>
          <line x1="8" y1="16" x2="24" y2="16" stroke="#5EEAD4" stroke-width="1.5" opacity="0.5"/>
          <line x1="10" y1="26" x2="22" y2="26" stroke="#5EEAD4" stroke-width="1.5" opacity="0.5"/>
        </svg>
        ChickenSV-Agent
      </h3>
      <el-button 
        type="primary" 
        circle
        @click="$emit('create')"
        title="New Chat"
        class="new-chat-btn"
      >
        <el-icon><Plus /></el-icon>
      </el-button>
    </div>
    
    <div class="session-list">
      <div
        v-for="session in sessions"
        :key="session.id"
        class="session-item"
        :class="{ active: session.id === currentSessionId }"
        @click="$emit('switch', session.id)"
      >
        <div class="session-icon">
          <el-icon><ChatLineRound /></el-icon>
        </div>
        <div class="session-info">
          <div class="session-title">{{ session.title }}</div>
          <div class="session-meta">
            {{ session.messageCount }} messages · {{ formatTime(session.updatedAt) }}
          </div>
        </div>
        <el-button
          v-if="sessions.length > 1"
          class="delete-btn"
          text
          circle
          size="small"
          @click.stop="$emit('delete', session.id)"
        >
          <el-icon><Delete /></el-icon>
        </el-button>
      </div>
      
      <div v-if="sessions.length === 0" class="empty-state">
        <svg class="empty-dna" width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M14,4 C14,10 8,14 8,24 C8,34 14,38 14,44" stroke="rgba(94,234,212,0.3)" stroke-width="2.5" stroke-linecap="round"/>
          <path d="M34,4 C34,10 40,14 40,24 C40,34 34,38 34,44" stroke="rgba(34,211,238,0.3)" stroke-width="2.5" stroke-linecap="round"/>
          <line x1="16" y1="10" x2="32" y2="10" stroke="rgba(94,234,212,0.2)" stroke-width="1.5"/>
          <line x1="14" y1="24" x2="34" y2="24" stroke="rgba(94,234,212,0.2)" stroke-width="1.5"/>
          <line x1="16" y1="38" x2="32" y2="38" stroke="rgba(94,234,212,0.2)" stroke-width="1.5"/>
        </svg>
        <p>No conversations yet</p>
        <el-button type="primary" @click="$emit('create')" class="start-btn">
          Start New Chat
        </el-button>
      </div>
    </div>
    
    <div class="sidebar-footer">
      <div class="gene-sequence">
        <span class="gene-base base-a">A</span>
        <span class="gene-base base-t">T</span>
        <span class="gene-base base-c">C</span>
        <span class="gene-base base-g">G</span>
      </div>
      <el-button text @click="goHome" class="home-btn">
        <el-icon><HomeFilled /></el-icon>
        Back to Home
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { 
  Plus, ChatLineRound, Delete, HomeFilled 
} from '@element-plus/icons-vue'
import type { ChatSession } from '@/stores/session'

interface Props {
  sessions: ChatSession[]
  currentSessionId: string
}

defineProps<Props>()

defineEmits<{
  create: []
  switch: [sessionId: string]
  delete: [sessionId: string]
}>()

const router = useRouter()

const goHome = () => {
  router.push('/')
}

const formatTime = (timestamp: string): string => {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  
  if (diff < 3600000) {
    const minutes = Math.floor(diff / 60000)
    return minutes < 1 ? 'Just now' : `${minutes}m ago`
  }
  
  if (diff < 86400000) {
    return `${Math.floor(diff / 3600000)}h ago`
  }
  
  if (diff < 604800000) {
    return `${Math.floor(diff / 86400000)}d ago`
  }
  
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
</script>

<style scoped>
.session-sidebar {
  width: 280px;
  height: 100vh;
  position: sticky;
  top: 0;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  color: #374151;
  border-right: 1px solid rgba(148, 163, 184, 0.12);
  box-shadow: 2px 0 12px rgba(15, 23, 42, 0.02);
}

.sidebar-header {
  padding: 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.3px;
  color: #374151;
}

.logo-dna {
  flex-shrink: 0;
}

.new-chat-btn {
  --el-button-bg-color: rgba(13, 148, 136, 0.06);
  --el-button-border-color: rgba(13, 148, 136, 0.14);
  --el-button-text-color: #0D9488;
  --el-button-hover-bg-color: rgba(13, 148, 136, 0.1);
  --el-button-hover-border-color: rgba(13, 148, 136, 0.22);
  --el-button-hover-text-color: #0D9488;
  color: #0D9488;
}

.new-chat-btn :deep(.el-icon) {
  color: #0D9488;
}

.session-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.3s ease;
  margin-bottom: 4px;
  border: 1px solid transparent;
}

.session-item:hover {
  background: rgba(13, 148, 136, 0.035);
}

.session-item.active {
  background: rgba(13, 148, 136, 0.055);
  border-color: rgba(13, 148, 136, 0.14);
}

.session-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(13, 148, 136, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #0D9488;
  flex-shrink: 0;
}

.session-item.active .session-icon {
  background: rgba(13, 148, 136, 0.1);
  color: #0D9488;
}

.session-info {
  flex: 1;
  min-width: 0;
}

.session-title {
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
  color: #374151;
}

.session-item.active .session-title {
  color: #0D9488;
}

.session-meta {
  font-size: 12px;
  color: #4B5563;
}

.delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
  color: #4B5563;
}

.session-item:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  color: #EF4444;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  text-align: center;
}

.empty-dna {
  margin-bottom: 16px;
}

.empty-state p {
  color: #4B5563;
  margin-bottom: 20px;
}

.start-btn {
  background: linear-gradient(135deg, #0D9488 0%, #06B6D4 100%) !important;
  border: none !important;
}

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.1);
}

.gene-sequence {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
  justify-content: center;
}

.gene-base {
  width: 22px;
  height: 22px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 600;
}

.base-a { background: rgba(13, 148, 136, 0.2); color: #14B8A6; }
.base-t { background: rgba(245, 158, 11, 0.2); color: #F59E0B; }
.base-c { background: rgba(139, 92, 246, 0.2); color: #8B5CF6; }
.base-g { background: rgba(239, 68, 68, 0.2); color: #EF4444; }

.home-btn {
  width: 100%;
  justify-content: center;
  color: #4B5563;
}

.home-btn:hover {
  color: #0D9488;
  background: rgba(13, 148, 136, 0.1) !important;
}
</style>
