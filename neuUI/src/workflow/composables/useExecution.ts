/**
 * 执行状态管理组合式函数
 * 管理工作流执行的实时状态、日志和进度
 */

import { ref, reactive, computed, onUnmounted } from 'vue'
import type { ExecutionInstance, NodeExecutionResult } from '../types'
import { useExecution as useExecutionAPI } from './useWorkflowAPI'

export interface ExecutionLog {
  timestamp: number
  level: 'info' | 'warning' | 'error' | 'debug'
  message: string
  nodeId?: string
  data?: any
}

export interface NodeStatus {
  nodeId: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  startTime?: number
  endTime?: number
  error?: string
  output?: any
}

export function useExecutionState() {
  const api = useExecutionAPI()
  
  // 当前执行实例
  const currentExecution = ref<ExecutionInstance | null>(null)
  
  // 节点状态映射
  const nodeStatuses = reactive<Record<string, NodeStatus>>({})
  
  // 执行日志
  const logs = ref<ExecutionLog[]>([])
  
  // 执行状态
  const isRunning = computed(() => currentExecution.value?.status === 'running')
  const isPaused = computed(() => currentExecution.value?.status === 'paused')
  const isCompleted = computed(() => currentExecution.value?.status === 'completed')
  const isFailed = computed(() => currentExecution.value?.status === 'failed')
  
  // 进度计算
  const progress = computed(() => {
    const statuses = Object.values(nodeStatuses)
    if (statuses.length === 0) return 0
    
    const completed = statuses.filter(s => 
      s.status === 'completed' || s.status === 'failed' || s.status === 'skipped'
    ).length
    
    return Math.round((completed / statuses.length) * 100)
  })
  
  // 当前执行节点
  const currentNodeId = computed(() => {
    const entry = Object.entries(nodeStatuses).find(([_, status]) => status.status === 'running')
    return entry ? entry[0] : null
  })
  
  // 轮询定时器
  let pollTimer: number | null = null
  
  // 添加日志
  function addLog(level: ExecutionLog['level'], message: string, nodeId?: string, data?: any) {
    logs.value.push({
      timestamp: Date.now(),
      level,
      message,
      nodeId,
      data,
    })
    
    // 限制日志数量
    if (logs.value.length > 1000) {
      logs.value = logs.value.slice(-500)
    }
  }
  
  // 更新节点状态
  function updateNodeStatus(nodeId: string, status: Partial<NodeStatus>) {
    if (!nodeStatuses[nodeId]) {
      nodeStatuses[nodeId] = {
        nodeId,
        status: 'pending',
      }
    }
    
    Object.assign(nodeStatuses[nodeId], status)
    
    // 添加日志
    if (status.status === 'running') {
      addLog('info', `节点 ${nodeId} 开始执行`, nodeId)
    } else if (status.status === 'completed') {
      addLog('info', `节点 ${nodeId} 执行完成`, nodeId, status.output)
    } else if (status.status === 'failed') {
      addLog('error', `节点 ${nodeId} 执行失败: ${status.error}`, nodeId)
    }
  }
  
  // 开始轮询执行状态
  function startPolling(executionId: string, interval = 1000) {
    stopPolling()
    
    const poll = async () => {
      try {
        const execution = await api.getExecution(executionId)
        currentExecution.value = execution
        
        // 更新节点状态
        if (execution.node_results) {
          for (const [nodeId, result] of Object.entries(execution.node_results)) {
            updateNodeStatus(nodeId, {
              status: result.status,
              startTime: result.start_time,
              endTime: result.end_time,
              error: result.error,
              output: result.output,
            })
          }
        }
        
        // 如果执行完成，停止轮询
        if (execution.status === 'completed' || execution.status === 'failed') {
          stopPolling()
          addLog(
            execution.status === 'completed' ? 'info' : 'error',
            `执行${execution.status === 'completed' ? '完成' : '失败'}`
          )
        }
      } catch (err) {
        addLog('error', `轮询执行状态失败: ${err}`)
      }
    }
    
    // 立即执行一次
    poll()
    
    // 设置定时器
    pollTimer = window.setInterval(poll, interval)
  }
  
  // 停止轮询
  function stopPolling() {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }
  
  // 开始执行
  async function startExecution(workflowId: string, input?: Record<string, any>) {
    // 重置状态
    resetState()
    
    addLog('info', '开始执行工作流...')
    
    try {
      const execution = await api.startExecution(workflowId, input)
      currentExecution.value = execution
      
      // 初始化所有节点状态为 pending
      if (execution.workflow_snapshot?.nodes) {
        for (const node of execution.workflow_snapshot.nodes) {
          updateNodeStatus(node.id, { status: 'pending' })
        }
      }
      
      // 开始轮询
      startPolling(execution.id)
      
      return execution
    } catch (err) {
      addLog('error', `启动执行失败: ${err}`)
      throw err
    }
  }
  
  // 暂停执行
  async function pauseExecution() {
    if (!currentExecution.value) return
    
    try {
      await api.pauseExecution(currentExecution.value.id)
      addLog('info', '执行已暂停')
    } catch (err) {
      addLog('error', `暂停执行失败: ${err}`)
      throw err
    }
  }
  
  // 恢复执行
  async function resumeExecution() {
    if (!currentExecution.value) return
    
    try {
      await api.resumeExecution(currentExecution.value.id)
      addLog('info', '执行已恢复')
      startPolling(currentExecution.value.id)
    } catch (err) {
      addLog('error', `恢复执行失败: ${err}`)
      throw err
    }
  }
  
  // 取消执行
  async function cancelExecution() {
    if (!currentExecution.value) return
    
    try {
      await api.cancelExecution(currentExecution.value.id)
      stopPolling()
      addLog('info', '执行已取消')
    } catch (err) {
      addLog('error', `取消执行失败: ${err}`)
      throw err
    }
  }
  
  // 重置状态
  function resetState() {
    stopPolling()
    currentExecution.value = null
    Object.keys(nodeStatuses).forEach(key => delete nodeStatuses[key])
    logs.value = []
  }
  
  // 获取节点执行结果
  function getNodeResult(nodeId: string): NodeExecutionResult | null {
    return currentExecution.value?.node_results?.[nodeId] || null
  }
  
  // 获取节点执行时间
  function getNodeDuration(nodeId: string): number | null {
    const status = nodeStatuses[nodeId]
    if (!status?.startTime) return null
    
    const endTime = status.endTime || Date.now()
    return endTime - status.startTime
  }
  
  // 清理
  onUnmounted(() => {
    stopPolling()
  })
  
  return {
    // 状态
    currentExecution,
    nodeStatuses,
    logs,
    
    // 计算属性
    isRunning,
    isPaused,
    isCompleted,
    isFailed,
    progress,
    currentNodeId,
    
    // 方法
    startExecution,
    pauseExecution,
    resumeExecution,
    cancelExecution,
    resetState,
    getNodeResult,
    getNodeDuration,
    addLog,
    updateNodeStatus,
  }
}