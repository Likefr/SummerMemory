/**
 * SummerMemory API 服务
 * 对接 memory_server.py (端口 11435)
 */

// API 基础地址 - 开发环境用代理，打包后用绝对地址
const API_BASE = import.meta.env.DEV 
  ? '/api/memory' 
  : 'https://ai.likefr.com/graphApi'

export async function fetchGraphData(threshold = 0.85) {
  const response = await fetch(`${API_BASE}/graph-data?threshold=${threshold}`)
  if (!response.ok) throw new Error('Failed to fetch graph data')
  return response.json()
}

export async function searchMemory(query, limit = 10) {
  const response = await fetch(`${API_BASE}/search?query=${encodeURIComponent(query)}&limit=${limit}`)
  if (!response.ok) throw new Error('Search failed')
  return response.json()
}

export async function getStats() {
  const response = await fetch(`${API_BASE}/stats`)
  if (!response.ok) throw new Error('Failed to fetch stats')
  return response.json()
}

export async function getVersion() {
  const response = await fetch(`${API_BASE}/version`)
  if (!response.ok) throw new Error('Failed to fetch version')
  return response.json()
}
