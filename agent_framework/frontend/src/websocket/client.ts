/**
 * WebSocket客户端
 *
 * 管理WebSocket连接，提供消息发送和接收功能
 */

export interface WebSocketMessage {
  id?: string
  type: string
  timestamp?: string
  payload: any
  access_token?: string
}

export class WebSocketClient {
  private ws: WebSocket | null = null
  private sessionId: string
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 2000
  private heartbeatInterval: number | null = null
  private reconnectTimer: number | null = null
  private intentionalClose = false
  private pendingMessages: Omit<WebSocketMessage, 'id' | 'timestamp'>[] = []

  public isConnected = false

  // 回调函数
  public onMessage?: (message: WebSocketMessage) => void
  public onConnect?: () => void
  public onDisconnect?: () => void
  public onError?: (error: Event) => void

  constructor(sessionId: string) {
    this.sessionId = sessionId
  }

  /**
   * 建立WebSocket连接
   */
  connect(): void {
    this.intentionalClose = false

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/ws/${this.sessionId}`

    console.log(`[WS] 正在连接: ${wsUrl}`)

    try {
      this.ws = new WebSocket(wsUrl)

      this.ws.onopen = () => {
        console.log('[WS] 连接成功')
        this.isConnected = true
        this.reconnectAttempts = 0
        this.startHeartbeat()
        this.flushPendingMessages()
        this.onConnect?.()
      }

      this.ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as WebSocketMessage
          this.onMessage?.(message)
        } catch (error) {
          console.error('[WS] 消息解析失败:', error)
        }
      }

      this.ws.onclose = (event) => {
        console.log(`[WS] 连接关闭 - Code: ${event.code}, Reason: ${event.reason || '无'}`)
        this.isConnected = false
        this.stopHeartbeat()

        if (!this.intentionalClose) {
          this.onDisconnect?.()
          this.scheduleReconnect()
        }
      }

      this.ws.onerror = (error) => {
        console.error('[WS] 连接错误')
        this.onError?.(error)
      }
    } catch (error) {
      console.error('[WS] 创建连接失败:', error)
      this.scheduleReconnect()
    }
  }

  /**
   * 断开WebSocket连接
   */
  disconnect(): void {
    this.intentionalClose = true
    this.stopHeartbeat()
    this.clearReconnectTimer()

    if (this.ws) {
      this.ws.close(1000, '用户主动断开')
      this.ws = null
    }
    this.isConnected = false
  }

  /**
   * 发送消息
   */
  send(message: Omit<WebSocketMessage, 'id' | 'timestamp'>): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      if (message.type === 'chat') {
        this.pendingMessages.push(message)
        if (this.pendingMessages.length > 10) {
          this.pendingMessages.shift()
        }
        console.warn('[WS] 未连接，消息已缓存，等待重连后发送')
      } else {
        console.warn('[WS] 未连接，无法发送消息')
      }
      return
    }

    const fullMessage: WebSocketMessage = {
      ...message,
      id: this.generateId(),
      timestamp: new Date().toISOString()
    }

    this.ws.send(JSON.stringify(fullMessage))
  }

  private flushPendingMessages(): void {
    while (this.pendingMessages.length > 0) {
      const msg = this.pendingMessages.shift()!
      this.send(msg)
    }
  }

  /**
   * 计划重连
   */
  private scheduleReconnect(): void {
    if (this.intentionalClose) return

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error(`[WS] 重连次数超过限制 (${this.maxReconnectAttempts})`)
      return
    }

    this.reconnectAttempts++
    const delay = Math.min(
      this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1),
      30000
    )

    console.log(`[WS] ${Math.round(delay)}ms后尝试第${this.reconnectAttempts}次重连...`)

    this.reconnectTimer = window.setTimeout(() => {
      this.connect()
    }, delay)
  }

  /**
   * 清除重连定时器
   */
  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  /**
   * 启动心跳检测
   */
  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatInterval = window.setInterval(() => {
      if (this.isConnected) {
        this.send({
          type: 'ping',
          payload: { timestamp: Date.now() }
        })
      }
    }, 30000)
  }

  /**
   * 停止心跳检测
   */
  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval)
      this.heartbeatInterval = null
    }
  }

  /**
   * 生成唯一ID
   */
  private generateId(): string {
    return `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }
}
