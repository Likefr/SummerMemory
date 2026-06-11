import { reactive, computed } from 'vue'

export const zh = {
  // Header
  files: '个文件',
  chunks: '个分块',
  refresh: '刷新',
  // Left panel
  dataSources: '数据源',
  searchPlaceholder: '搜索记忆...',
  fileSection: '文件',
  legendSection: '图例',
  fileNode: '文件节点',
  chunkNode: '分块节点',
  relation: '关联线',
  // Right panel
  configuration: '配置',
  nodePreview: '节点预览',
  connections: '连接数：',
  hoverToPreview: '悬停节点以预览',
  points: '点',
  colorColumn: '颜色列',
  sizeColumn: '大小列',
  showLabels: '显示标签',
  appearance: '外观',
  background: '背景色',
  nodeSize: '节点大小',
  linkOpacity: '连线透明度',
  simulation: '模拟',
  repulsion: '斥力',
  linkDistance: '连线距离',
  reheat: '重启',
  fit: '适配',
  view: '视图',
  showLinks: '显示连线',
  linkWidth: '连线宽度',
  labelFontSize: '标签字号',
  filter: '过滤',
  minChunks: '最小分块数',
  minConnections: '最小连接数',
  applyFilter: '应用过滤',
  resetFilter: '重置过滤',
  // Section headers
  appearanceSection: '外观',
  labelsSection: '标签',
  simulationSection: '模拟',
  timelineSection: '时间轴',
  // Auto Refresh
  autoRefresh: '自动刷新',
  enableRefresh: '启用',
  interval: '间隔',
  newVersion: '有新版本',
  // Empty / Loading
  noData: '暂无数据',
  loadData: '加载数据',
  loadingGraph: '加载图谱中...',
  // Tooltip
  chunkLabel: '分块',
  // Preview
  kb: 'KB',
  // Legend
  legendMemory: '记忆文件',
  legendProject: '项目文档',
  legendConfig: '配置/规则',
  legendWork: '工作记录',
  legendRelation: '关联关系',
  // Timeline
  clearFilter: '清除筛选',
}

export const en = {
  files: ' files',
  chunks: ' chunks',
  refresh: 'Refresh',
  dataSources: 'Data Sources',
  searchPlaceholder: 'Search memory...',
  fileSection: 'Files',
  legendSection: 'Legend',
  fileNode: 'File Node',
  chunkNode: 'Chunk Node',
  relation: 'Relation',
  configuration: 'Configuration',
  nodePreview: 'Node Preview',
  connections: 'Connections: ',
  hoverToPreview: 'Hover over a node to preview',
  points: 'Points',
  colorColumn: 'Color Column',
  sizeColumn: 'Size Column',
  showLabels: 'Show Labels',
  appearance: 'Appearance',
  background: 'Background',
  nodeSize: 'Node Size',
  linkOpacity: 'Link Opacity',
  simulation: 'Simulation',
  repulsion: 'Repulsion',
  linkDistance: 'Link Distance',
  reheat: 'Reheat',
  fit: 'Fit',
  view: 'View',
  showLinks: 'Show Links',
  linkWidth: 'Link Width',
  labelFontSize: 'Label Font Size',
  filter: 'Filter',
  minChunks: 'Min Chunks',
  minConnections: 'Min Connections',
  applyFilter: 'Apply Filter',
  resetFilter: 'Reset Filter',
  // Section headers
  appearanceSection: 'Appearance',
  labelsSection: 'Labels',
  simulationSection: 'Simulation',
  timelineSection: 'Timeline',
  // Auto Refresh
  autoRefresh: 'Auto Refresh',
  enableRefresh: 'Enable',
  interval: 'Interval',
  newVersion: 'New Version',
  noData: 'No data loaded',
  loadData: 'Load Data',
  loadingGraph: 'Loading graph...',
  chunkLabel: 'chunk',
  kb: 'KB',
  // Legend
  legendMemory: 'Memory Files',
  legendProject: 'Project Docs',
  legendConfig: 'Config/Rules',
  legendWork: 'Work Records',
  legendRelation: 'Relations',
  // Timeline
  clearFilter: 'Clear',
}

const state = reactive({
  lang: localStorage.getItem('memgraph-lang') || 'zh'
})

const messages = computed(() => state.lang === 'zh' ? zh : en)

export function currentLang() {
  return state.lang
}

export function setLang(lang) {
  state.lang = lang
  localStorage.setItem('memgraph-lang', lang)
}

export function toggleLang() {
  const next = state.lang === 'zh' ? 'en' : 'zh'
  setLang(next)
  return next
}

export function t(key) {
  return messages.value[key] ?? key
}

export function useI18n() {
  return { t, currentLang, setLang, toggleLang, state }
}
