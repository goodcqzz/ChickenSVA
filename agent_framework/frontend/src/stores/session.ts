import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

export interface ChatSession {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  messageCount: number
  workspaceId?: string
  workspaceType?: 'query' | 'imputation' | null
}

const STORAGE_KEY = 'agent_framework_sessions'
const CURRENT_SESSION_KEY = 'agent_framework_current_session'

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<ChatSession[]>(loadFromStorage())
  const currentSessionId = ref<string>(loadCurrentSession())
  const currentWorkspaceId = ref<string>('')
  const workspaceType = ref<'query' | 'imputation' | null>(null)
  const workspaceAction = ref<string>('')

  function loadFromStorage(): ChatSession[] {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        return JSON.parse(stored)
      }
    } catch (e) {
      console.error('Failed to load sessions from storage:', e)
    }
    return []
  }

  function loadCurrentSession(): string {
    try {
      return localStorage.getItem(CURRENT_SESSION_KEY) || ''
    } catch (e) {
      return ''
    }
  }

  function saveToStorage() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.value))
      localStorage.setItem(CURRENT_SESSION_KEY, currentSessionId.value)
    } catch (e) {
      console.error('Failed to save sessions to storage:', e)
    }
  }

  watch(sessions, saveToStorage, { deep: true })
  watch(currentSessionId, saveToStorage)

  const currentSession = computed(() =>
    sessions.value.find(s => s.id === currentSessionId.value)
  )

  const hasWorkspace = computed(() => !!currentWorkspaceId.value)

  const isImputationWorkspace = computed(() => workspaceType.value === 'imputation')

  const _persistWorkspaceToSession = (
    sessionId: string,
    workspaceId: string,
    type: 'query' | 'imputation' | null
  ) => {
    const session = sessions.value.find(s => s.id === sessionId)
    if (!session) return
    if (workspaceId && type) {
      session.workspaceId = workspaceId
      session.workspaceType = type
    } else {
      delete session.workspaceId
      delete session.workspaceType
    }
    session.updatedAt = new Date().toISOString()
  }

  const _applySessionWorkspace = (sessionId: string) => {
    const session = sessions.value.find(s => s.id === sessionId)
    if (session?.workspaceId && session.workspaceType) {
      currentWorkspaceId.value = session.workspaceId
      workspaceType.value = session.workspaceType
    } else {
      currentWorkspaceId.value = ''
      workspaceType.value = null
    }
    workspaceAction.value = ''
  }

  const createSession = (title: string = 'New Chat') => {
    const session: ChatSession = {
      id: `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      title,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      messageCount: 0,
    }
    sessions.value.unshift(session)
    currentSessionId.value = session.id
    _applySessionWorkspace(session.id)
    return session.id
  }

  const switchSession = (sessionId: string) => {
    currentSessionId.value = sessionId
    _applySessionWorkspace(sessionId)
  }

  const deleteSession = (sessionId: string) => {
    const index = sessions.value.findIndex(s => s.id === sessionId)
    if (index > -1) {
      sessions.value.splice(index, 1)
      if (currentSessionId.value === sessionId) {
        currentSessionId.value = sessions.value[0]?.id || ''
        if (currentSessionId.value) {
          _applySessionWorkspace(currentSessionId.value)
        } else {
          clearWorkspace()
        }
      }
    }
  }

  const updateSessionTitle = (sessionId: string, title: string) => {
    const session = sessions.value.find(s => s.id === sessionId)
    if (session) {
      session.title = title
      session.updatedAt = new Date().toISOString()
    }
  }

  const incrementMessageCount = (sessionId: string) => {
    const session = sessions.value.find(s => s.id === sessionId)
    if (session) {
      session.messageCount++
      session.updatedAt = new Date().toISOString()
    }
  }

  const setWorkspace = (workspaceId: string, type: 'query' | 'imputation', action?: string) => {
    currentWorkspaceId.value = workspaceId
    workspaceType.value = type
    workspaceAction.value = action || ''
    if (currentSessionId.value) {
      _persistWorkspaceToSession(currentSessionId.value, workspaceId, type)
    }
  }

  const clearWorkspace = () => {
    currentWorkspaceId.value = ''
    workspaceType.value = null
    workspaceAction.value = ''
    if (currentSessionId.value) {
      _persistWorkspaceToSession(currentSessionId.value, '', null)
    }
  }

  return {
    sessions,
    currentSessionId,
    currentWorkspaceId,
    workspaceType,
    workspaceAction,
    currentSession,
    hasWorkspace,
    isImputationWorkspace,
    createSession,
    switchSession,
    deleteSession,
    updateSessionTitle,
    incrementMessageCount,
    setWorkspace,
    clearWorkspace,
    applySessionWorkspace: _applySessionWorkspace,
  }
})
