<template>
  <div class="app" :class="{ 'theme-dark': isDark }">
    <!-- 顶部导航 -->
    <header class="header">
      <div class="header-left">
        <div class="logo">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/>
            <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
          </svg>
        </div>
        <div class="project-info">
          <div class="project-name" @click="editing = true" v-if="!editing">
            {{ projectName }}
          </div>
          <input v-else v-model="projectName" @blur="editing = false" @keyup.enter="editing = false" class="project-input" />
          <div class="project-version">{{ currentVersion }}</div>
        </div>
      </div>
      <div class="header-center">
        <span class="stat"><span class="stat-value">{{ stats.total_files || 0 }}</span>{{ t('files') }}</span>
        <span class="stat"><span class="stat-value">{{ stats.total_chunks || 0 }}</span>{{ t('chunks') }}</span>
        <span class="stat stat-time">{{ searchTime > 0 ? searchTime + 'ms' : '' }}</span>
      </div>
      <div class="header-right">
        <button class="header-btn theme-toggle" @click="toggleTheme" :title="isDark ? 'Light mode' : 'Dark mode'">
          <svg v-if="isDark" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
          </svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
        </button>

        <button v-if="hasUpdate" class="header-btn btn-update" @click="handleUpdate">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
          {{ t('newVersion') }}
        </button>
        <button class="header-btn btn-lang" @click="toggleLang">{{ i18nState.lang === 'zh' ? 'EN' : '中' }}</button>
        <button class="header-btn btn-primary" @click="refreshData">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
          {{ t('refresh') }}
        </button>
      </div>
    </header>

    <div class="main">
      <!-- 左侧面板 -->
      <aside class="sidebar-left" :class="{ collapsed: leftCollapsed }">
        <div class="panel-header">
          <h3>{{ t('dataSources') }}</h3>
          <button class="btn-icon" @click="leftCollapsed = !leftCollapsed">
            <svg :width="12" :height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline :points="leftCollapsed ? '9 18 15 12 9 6' : '15 18 9 12 15 6'"/>
            </svg>
          </button>
        </div>

        <div class="panel-content" v-if="!leftCollapsed">
          <!-- 搜索 -->
          <div class="search-box">
            <div class="search-input-wrap">
              <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <input v-model="searchQuery" @input="debounceSearch" :placeholder="t('searchPlaceholder')" class="search-input" />
            </div>
          </div>

          <!-- 文件列表 -->
          <div class="section">
            <div class="section-header" @click="filesExpanded = !filesExpanded">
              <span>{{ t('fileSection') }} <span class="section-count">{{ fileNodes.length }}</span></span>
              <svg :width="10" :height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline :points="filesExpanded ? '6 9 12 15 18 9' : '6 15 12 9 18 15'"/>
              </svg>
            </div>
            <div class="file-list" v-if="filesExpanded">
              <div v-for="file in fileNodes" :key="file.id"
                   :class="['file-item', { active: selectedFile === file.id }]"
                   @click="selectFile(file)">
                <span class="file-dot" :style="{ background: file.color }"></span>
                <span class="file-name">{{ file.label }}</span>
                <span class="file-chunks">{{ file.chunks }}c</span>
              </div>
            </div>
          </div>
        </div>
      </aside>

      <!-- 中间图谱 -->
      <main class="graph-area">
        <div class="graph-container" ref="graphContainer"></div>

        <!-- 浮动图例 -->
        <div class="floating-legend" v-click-outside="() => legendExpanded = false">
          <div class="legend-toggle" @click="legendExpanded = !legendExpanded">
            {{ legendExpanded ? '' : t('legendSection') }}
            <svg v-if="!legendExpanded" :width="10" :height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-left:4px">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </div>
          <div class="legend-content" v-if="legendExpanded">
            <div class="legend-item">
              <span class="legend-dot" style="background: #3B82F6"></span>
              <span>{{ t('legendMemory') }}</span>
            </div>
            <div class="legend-item">
              <span class="legend-dot" style="background: #10B981"></span>
              <span>{{ t('legendProject') }}</span>
            </div>
            <div class="legend-item">
              <span class="legend-dot" style="background: #F59E0B"></span>
              <span>{{ t('legendConfig') }}</span>
            </div>
            <div class="legend-item">
              <span class="legend-dot" style="background: #8B5CF6"></span>
              <span>{{ t('legendWork') }}</span>
            </div>
            <div class="legend-item">
              <span class="legend-line"></span>
              <span>{{ t('legendRelation') }}</span>
            </div>
          </div>
        </div>

        <!-- 工具提示 -->
        <div class="tooltip" v-if="tooltip" :style="tooltipStyle">
          <div class="tip-header">
            <span class="tip-path">{{ tooltip.path }}</span>
            <span class="tip-type">{{ tooltip.type }}</span>
          </div>
          <div class="tip-meta">{{ tooltip.meta }}</div>
          <div class="tip-content">{{ tooltip.content }}</div>
        </div>

        <!-- 空状态 -->
        <div class="empty-state" v-if="!loading && nodes.length === 0">
          <svg class="empty-icon" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
          </svg>
          <div class="empty-text">{{ t('noData') }}</div>
          <button class="header-btn btn-primary" @click="refreshData">{{ t('loadData') }}</button>
        </div>

        <!-- 加载状态 -->
        <div class="loading-state" v-if="loading">
          <div class="spinner"></div>
        </div>
      </main>

      <!-- 右侧面板 -->
      <aside class="sidebar-right" :class="{ collapsed: rightCollapsed, open: sidebarOpen }">
        <div class="panel-header">
          <button class="btn-icon" @click="rightCollapsed = !rightCollapsed">
            <svg :width="12" :height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline :points="rightCollapsed ? '9 18 15 12 9 6' : '15 18 9 12 15 6'"/>
            </svg>
          </button>
          <h3>{{ t('configuration') }}</h3>
        </div>

        <div class="panel-content" v-if="!rightCollapsed">
          <!-- 预览面板 -->
          <div class="section">
            <div class="section-header" @click="previewExpanded = !previewExpanded">
              <span>{{ t('nodePreview') }}</span>
              <svg :width="10" :height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline :points="previewExpanded ? '6 9 12 15 18 9' : '6 15 12 9 18 15'"/>
              </svg>
            </div>
            <div class="preview-panel" v-if="previewExpanded">
              <div v-if="hoveredNode" class="preview-card">
                <div class="preview-title">{{ hoveredNode.label || hoveredNode.id }}</div>
                <div class="preview-meta">
                  <span class="preview-badge" :style="{ background: hoveredNode.color }">{{ hoveredNode.type }}</span>
                  <span v-if="hoveredNode.type === 'file'">{{ hoveredNode.chunks || 0 }} {{ t('chunks').trim() }}</span>
                  <span v-if="hoveredNode.type === 'file'">{{ ((hoveredNode.fileSize || 0) / 1024).toFixed(1) }} {{ t('kb') }}</span>
                </div>
                <div class="preview-path" v-if="hoveredNode.path">{{ hoveredNode.path }}</div>
                <div class="preview-content" v-if="hoveredNode.content">{{ hoveredNode.content.substring(0, 200) }}...</div>
                <div class="preview-links" v-if="hoveredNode.type === 'file'">
                  <strong>{{ t('connections') }}</strong>{{ getNodeConnections(hoveredNode.id) }}
                </div>
              </div>
              <div v-else class="preview-empty">{{ t('hoverToPreview') }}</div>
            </div>
          </div>

          <!-- 外观 -->
          <div class="section">
            <div class="section-header" @click="appearanceExpanded = !appearanceExpanded">
              <span>{{ t('appearanceSection') }}</span>
              <svg :width="10" :height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline :points="appearanceExpanded ? '6 9 12 15 18 9' : '6 15 12 9 18 15'"/>
              </svg>
            </div>
            <div class="config-group" v-if="appearanceExpanded">
              <div class="config-item">
                <label>节点大小范围</label>
                <div class="dual-slider">
                  <input type="range" v-model.number="sizeRangeMin" min="1" max="50" step="1" class="config-range dual-range" />
                  <input type="range" v-model.number="sizeRangeMax" min="1" max="50" step="1" class="config-range dual-range" />
                </div>
                <span class="range-value">{{ sizeRangeMin }} ~ {{ sizeRangeMax }}</span>
              </div>
              <div class="config-item">
                <label>{{ t('showLinks') }}</label>
                <input type="checkbox" v-model="showLinks" class="config-switch" />
              </div>
              <div class="config-item">
                <label>{{ t('linkWidth') }}</label>
                <input type="range" v-model.number="linkWidth" min="0.1" max="3" step="0.1" class="config-range" />
                <span class="range-value">{{ linkWidth.toFixed(1) }}</span>
              </div>
              <div class="config-item">
                <label>连线颜色</label>
                <div class="color-presets">
                  <div
                    v-for="c in linkColorPresets"
                    :key="c"
                    class="color-swatch"
                    :class="{ active: linkDefaultColor === c }"
                    :style="{ background: c }"
                    @click="linkDefaultColor = c"
                  ></div>
                </div>
              </div>
            </div>
          </div>

          <!-- 标签 -->
          <div class="section">
            <div class="section-header" @click="labelsExpanded = !labelsExpanded">
              <span>{{ t('labelsSection') }}</span>
              <svg :width="10" :height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline :points="labelsExpanded ? '6 9 12 15 18 9' : '6 15 12 9 18 15'"/>
              </svg>
            </div>
            <div class="config-group" v-if="labelsExpanded">
              <div class="config-item">
                <label>{{ t('showLabels') }}</label>
                <input type="checkbox" v-model="showLabels" class="config-switch" />
              </div>
              <div class="config-item">
                <label>{{ t('labelFontSize') }}</label>
                <input type="range" v-model.number="pointLabelFontSize" min="8" max="24" step="1" class="config-range" />
                <span class="range-value">{{ pointLabelFontSize }}px</span>
              </div>
              <div class="config-item">
                <label>动态标签</label>
                <input type="checkbox" v-model="showDynamicLabels" class="config-switch" />
              </div>
              <div class="config-item">
                <label>顶部标签</label>
                <input type="checkbox" v-model="showTopLabels" class="config-switch" />
              </div>
              <div class="config-item" v-if="showTopLabels">
                <label>顶部标签数量</label>
                <input type="range" v-model.number="showTopLabelsLimit" min="5" max="100" step="5" class="config-range" />
                <span class="range-value">{{ showTopLabelsLimit }}</span>
              </div>
              <div class="config-item">
                <label>标签颜色</label>
                <div class="color-presets">
                  <div
                    v-for="c in labelColorPresets"
                    :key="c"
                    class="color-swatch"
                    :class="{ active: pointLabelColor === c }"
                    :style="{ background: c }"
                    @click="pointLabelColor = c"
                  ></div>
                </div>
              </div>
            </div>
          </div>

          <!-- 模拟 -->
          <div class="section">
            <div class="section-header" @click="simulationExpanded = !simulationExpanded">
              <span>{{ t('simulationSection') }}</span>
              <svg :width="10" :height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline :points="simulationExpanded ? '6 9 12 15 18 9' : '6 15 12 9 18 15'"/>
              </svg>
            </div>
            <div class="config-group" v-if="simulationExpanded">
              <div class="config-item">
                <label>斥力</label>
                <input type="range" v-model.number="simRepulsion" min="0.1" max="5" step="0.1" class="config-range" />
                <span class="range-value">{{ simRepulsion.toFixed(1) }}</span>
              </div>
              <div class="config-item">
                <label>引力</label>
                <input type="range" v-model.number="simGravity" min="0" max="2" step="0.05" class="config-range" />
                <span class="range-value">{{ simGravity.toFixed(2) }}</span>
              </div>
              <div class="config-item">
                <label>摩擦力</label>
                <input type="range" v-model.number="simFriction" min="0.5" max="0.99" step="0.01" class="config-range" />
                <span class="range-value">{{ simFriction.toFixed(2) }}</span>
              </div>
              <div class="config-item">
                <label>衰减</label>
                <input type="range" v-model.number="simDecay" min="1000" max="20000" step="500" class="config-range" />
                <span class="range-value">{{ simDecay }}</span>
              </div>
              <div class="config-item">
                <label>{{ t('linkDistance') }}</label>
                <input type="range" v-model.number="simLinkDistance" min="1" max="100" step="1" class="config-range" />
                <span class="range-value">{{ simLinkDistance }}</span>
              </div>
              <div class="btn-row" style="flex-wrap: wrap;">
                <button class="header-btn btn-ghost" @click="simStart">启动</button>
                <button class="header-btn btn-ghost" @click="simPause">暂停</button>
                <button class="header-btn btn-ghost" @click="simUnpause">继续</button>
                <button class="header-btn btn-ghost" @click="fitToScreen">适配视图</button>
                <button class="header-btn btn-ghost" @click="reheatSimulation">重新加热</button>
              </div>
            </div>
          </div>

          <!-- 过滤 -->
          <div class="section">
            <div class="section-header" @click="filterExpanded = !filterExpanded">
              <span>{{ t('filter') }}</span>
              <svg :width="10" :height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline :points="filterExpanded ? '6 9 12 15 18 9' : '6 15 12 9 18 15'"/>
              </svg>
            </div>
            <div class="config-group" v-if="filterExpanded">
              <div class="config-item">
                <label>{{ t('minChunks') }}</label>
                <input type="range" v-model.number="minChunks" min="1" max="20" class="config-range" />
                <span class="range-value">{{ minChunks }}</span>
              </div>
              <div class="config-item">
                <label>{{ t('minConnections') }}</label>
                <input type="range" v-model.number="minConnections" min="0" max="50" class="config-range" />
                <span class="range-value">{{ minConnections }}</span>
              </div>
              <div class="btn-row">
                <button class="header-btn btn-ghost" @click="applyFilter">{{ t('applyFilter') }}</button>
                <button class="header-btn btn-ghost" @click="resetFilter">{{ t('resetFilter') }}</button>
              </div>
            </div>
          </div>

          <!-- 时间轴 -->
          <div class="section">
            <div class="section-header" @click="timelineExpanded = !timelineExpanded">
              <span>{{ t('timelineSection') }}</span>
              <svg :width="10" :height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline :points="timelineExpanded ? '6 9 12 15 18 9' : '6 15 12 9 18 15'"/>
              </svg>
            </div>
            <div class="config-group" v-if="timelineExpanded">
              <div class="timeline-container">
                <div
                  v-for="item in timelineData"
                  :key="item.date"
                  class="timeline-bar-wrapper"
                  @click="selectTimelineDate(item.date)"
                  :class="{ active: selectedDate === item.date }"
                >
                  <div class="timeline-date">{{ item.date.slice(5) }}</div>
                  <div class="timeline-bar-bg">
                    <div
                      class="timeline-bar"
                      :style="{ height: (item.count / maxTimelineCount * 100) + '%', background: selectedDate === item.date ? '#3B82F6' : '#60A5FA' }"
                    ></div>
                  </div>
                  <div class="timeline-count">{{ item.count }}</div>
                </div>
              </div>
              <div v-if="selectedDate" class="timeline-info">
                <div class="timeline-selected">{{ selectedDate }}</div>
                <div class="timeline-files">
                  <span v-for="f in selectedFiles" :key="f" class="timeline-file-tag">{{ f }}</span>
                </div>
                <button class="header-btn btn-ghost" style="margin-top:8px;width:100%" @click="clearTimelineFilter">{{ t('clearFilter') }}</button>
              </div>
            </div>
          </div>

          <!-- 自动刷新 -->
          <div class="section">
            <div class="section-header" @click="refreshExpanded = !refreshExpanded">
              <span>{{ t('autoRefresh') }}</span>
              <svg :width="10" :height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline :points="refreshExpanded ? '6 9 12 15 18 9' : '6 15 12 9 18 15'"/>
              </svg>
            </div>
            <div class="config-group" v-if="refreshExpanded">
              <div class="config-item">
                <label>{{ t('enableRefresh') }}</label>
                <input type="checkbox" v-model="autoRefresh" class="config-switch" />
              </div>
              <div class="config-item" v-if="autoRefresh">
                <label>{{ t('interval') }}</label>
                <input type="range" v-model.number="refreshInterval" min="500" max="5000" step="500" class="config-range" />
                <span class="range-value">{{ refreshInterval }}ms</span>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, watch, shallowRef, nextTick } from 'vue'
import { Cosmograph } from '@cosmograph/cosmograph'
import { fetchGraphData, searchMemory, getStats, getVersion } from '../api/memory'

const TIMELINE_API = import.meta.env.DEV
  ? '/api/memory/timeline'
  : 'https://ai.likefr.com/graphApi/timeline'
import { useI18n } from '../i18n'

const { t, toggleLang, currentLang, state: i18nState } = useI18n()

// Theme
const isDark = ref(localStorage.getItem('memgraph-theme') !== 'light')
function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem('memgraph-theme', isDark.value ? 'dark' : 'light')
  updateGraphBg()
}
function updateGraphBg() {
  if (graph.value) {
    updateGraphConfig({ backgroundColor: isDark.value ? '#0A0A0C' : '#F7F6F3' })
  }
}

// State
const graphContainer = ref(null)
const graph = shallowRef(null)
const graphFullConfig = ref({})
const nodes = ref([])
const links = ref([])
const stats = ref({})
const loading = ref(false)
const searchQuery = ref('')
const searchTime = ref(0)
const selectedFile = ref(null)
const hoveredNode = ref(null)
const tooltip = ref(null)
const tooltipStyle = ref({})
const hasUpdate = ref(false)
let versionCheckTimer = null

// UI State
const editing = ref(false)
const projectName = ref('SummerMemory Graph')
const leftCollapsed = ref(false)
const rightCollapsed = ref(true)
const sidebarOpen = ref(false)
const filesExpanded = ref(true)
const legendExpanded = ref(true)
const appearanceExpanded = ref(true)
const labelsExpanded = ref(false)
const simulationExpanded = ref(false)
const previewExpanded = ref(true)
const filterExpanded = ref(false)
const refreshExpanded = ref(false)

// Config - 外观
const sizeRangeMin = ref(2)
const sizeRangeMax = ref(20)
const showLinks = ref(true)
const linkWidth = ref(1)
const linkDefaultColor = ref('rgba(100, 180, 255, 0.3)')
const linkColorPresets = [
  'rgba(100, 180, 255, 0.3)',
  'rgba(100, 180, 255, 0.5)',
  'rgba(150, 200, 255, 0.3)',
  'rgba(80, 120, 200, 0.3)',
  'rgba(200, 200, 200, 0.2)',
]

// Config - 标签
const showLabels = ref(true)
const pointLabelFontSize = ref(11)
const showDynamicLabels = ref(false)
const showTopLabels = ref(true)
const showTopLabelsLimit = ref(20)
const pointLabelColor = ref('#94a3b8')
const labelColorPresets = [
  '#94a3b8', '#e2e8f0', '#60a5fa', '#93c5fd', '#ffffff',
]

// Config - 模拟
const simRepulsion = ref(2.7)
const simGravity = ref(1.0)
const simFriction = ref(0.91)
const simDecay = ref(7500)
const simLinkDistance = ref(53)

// Config - 过滤
const minChunks = ref(1)
const minConnections = ref(0)

// Config - 其他
const autoRefresh = ref(false)
const refreshInterval = ref(1000)
const searching = ref(false)

// WebSocket & timeline
let refreshTimer = null
let ws = null
let wsReconnectTimer = null
const timelineExpanded = ref(false)
const timelineData = ref([])
const selectedDate = ref('')
const selectedFiles = ref([])
const maxTimelineCount = computed(() => Math.max(...timelineData.value.map(t => t.count), 1))
let searchTimer = null
const currentVersion = ref('v260608.1920')

// Colors — 按路径前缀分类
const CATEGORY_COLORS = {
  '记忆文件': '#3B82F6',   // 蓝
  '项目文档': '#10B981',   // 绿
  '配置/规则': '#F59E0B',  // 黄
  '工作记录': '#8B5CF6',   // 紫
}

function getCategory(node) {
  const path = node.path || node.id || ''
  if (path.includes('rules-') || path.includes('todo') || path.includes('sealed') || path.includes('home-power') || path.includes('browser-access')) return '配置/规则'
  if (path.includes('router-monitor') || path.includes('next-ecdis') || path.includes('worksnap') || path.includes('summer-voice') || path.includes('clash')) return '项目文档'
  if (/2026-\d{2}-\d{2}/.test(path) && !path.includes('dreaming')) return '工作记录'
  if (path.startsWith('memory/') || path === 'MEMORY.md') return '记忆文件'
  return '记忆文件'
}

function getColor(node) {
  return CATEGORY_COLORS[getCategory(node)] || '#3B82F6'
}

// Computed
const fileNodes = computed(() => {
  return nodes.value.filter(n => n.type === 'file')
})

// ── 构建 Cosmograph 数据格式 ──
function buildPoints(nodeList) {
  return nodeList.map((n, i) => ({
    id: String(n.id),
    index: i,
    label: n.label || n.name || n.id,
    color: n.color || '#3B82F6',
    size: Math.min(Math.sqrt((n.chunks || 1)) * 4, sizeRangeMax.value),
    _raw: n,
  }))
}

function buildLinks(linkList, visible = true) {
  const idToIndex = new Map()
  nodes.value.forEach((n, i) => idToIndex.set(String(n.id), i))
  return linkList.map(l => ({
    source: String(l.source),
    target: String(l.target),
    sourceIndex: idToIndex.get(String(l.source)) ?? 0,
    targetIndex: idToIndex.get(String(l.target)) ?? 0,
  }))
}

// ── 加载时间轴数据 ──
async function loadTimeline() {
  try {
    const res = await fetch(TIMELINE_API)
    const data = await res.json()
    timelineData.value = data.timeline || []
  } catch (err) {
    console.error('Timeline load failed:', err)
  }
}

// ── 时间轴筛选 ──
function selectTimelineDate(date) {
  if (selectedDate.value === date) {
    clearTimelineFilter()
    return
  }
  selectedDate.value = date
  const item = timelineData.value.find(t => t.date === date)
  selectedFiles.value = item ? item.files : []
  // 高亮该日期的节点
  applyHighlight((n) => selectedFiles.value.some(f => n.path && n.path.includes(f.replace('.md', ''))))
}

function clearTimelineFilter() {
  selectedDate.value = ''
  selectedFiles.value = []
  applyHighlight(() => false)
}

// ── 高亮节点（重新上色 + 缩放） ──
function applyHighlight(highlightFn) {
  if (!graph.value) return
  const pts = buildPoints(nodes.value).map(p => ({
    ...p,
    color: highlightFn(p._raw) ? '#ffffff' : (p.color),
  }))
  updateGraphConfig({ points: pts })
}

// ── 加载数据 ──
async function loadData() {
  console.log('[Graph] loadData called')
  loading.value = true
  const startTime = performance.now()
  try {
    const [graphData, statsData] = await Promise.all([
      fetchGraphData(),
      getStats()
    ])
    searchTime.value = Math.round(performance.now() - startTime)

    stats.value = statsData
    const newNodes = graphData.nodes.map((n) => ({
      ...n,
      color: getColor(n),
    }))
    links.value = graphData.links

    if (!graph.value) {
      nodes.value = newNodes
      await nextTick()
      initGraph()
    } else {
      nodes.value = newNodes
      updateGraphData()
    }
  } catch (err) {
    console.error('[Graph] Failed to load data:', err)
  } finally {
    loading.value = false
    loadTimeline()
  }
}

// ── 初始化 Cosmograph ──
function initGraph() {
  if (!graphContainer.value || nodes.value.length === 0) return

  const container = graphContainer.value
  container.innerHTML = ''

  try {
    if (graph.value) {
      graph.value.destroy()
      graph.value = null
    }

    const bgColor = isDark.value ? '#0A0A0C' : '#F7F6F3'

    const g = new Cosmograph(container, {
      points: buildPoints(nodes.value),
      pointIdBy: 'id',
      pointIndexBy: 'index',
      pointLabelBy: 'label',
      pointColorBy: 'color',
      links: buildLinks(links.value, showLinks.value),
      linkSourceBy: 'source',
      linkTargetBy: 'target',
      linkSourceIndexBy: 'sourceIndex',
      linkTargetIndexBy: 'targetIndex',
      linkWidthStrategy: 'single',
      linkColorStrategy: 'single',
      enableSimulation: true,
      simulationRepulsion: simRepulsion.value,
      simulationGravity: simGravity.value,
      simulationFriction: simFriction.value,
      simulationDecay: simDecay.value,
      simulationLinkDistance: simLinkDistance.value,
      simulationLinkSpring: 1,
      backgroundColor: bgColor,
      pointDefaultColor: '#3B82F6',
      pointSizeRange: [sizeRangeMin.value, sizeRangeMax.value],
      linkDefaultColor: linkDefaultColor.value,
      linkDefaultWidth: linkWidth.value,
      showLabels: showLinks.value,
      pointLabelFontSize: pointLabelFontSize.value,
      showDynamicLabels: showDynamicLabels.value,
      showTopLabels: showTopLabels.value,
      showTopLabelsLimit: showTopLabelsLimit.value,
      showHoveredPointLabel: true,
      pointLabelColor: pointLabelColor.value,
      selectPointOnClick: 'single',
      enableDrag: true,
      focusPointOnClick: true,
      onPointMouseOver: (idx) => { try { graph.value?.setPinnedPoints([idx]) } catch(e) {} },
      onPointMouseOut: () => { try { graph.value?.setPinnedPoints([]) } catch(e) {} },
      onGraphRebuilt: () => {
        console.log('[Graph] Graph rebuilt')
      },
    })

    // ── Click 预览 — 区分点击和拖拽 ──
    let _downX = 0, _downY = 0, _downTime = 0
    let _previewFitTimer = null
    container.addEventListener('pointerdown', (e) => {
      _downX = e.clientX
      _downY = e.clientY
      _downTime = Date.now()
    })
    container.addEventListener('pointerup', async (e) => {
      // 移动超过 5px 或超过 300ms 算拖拽，不触发点击
      const dx = e.clientX - _downX, dy = e.clientY - _downY
      const dist = Math.sqrt(dx * dx + dy * dy)
      const elapsed = Date.now() - _downTime
      if (dist > 30 || elapsed > 1000) return

      if (!graph.value) return
      await new Promise(r => setTimeout(r, 200))
      try {
        const indices = graph.value.getSelectedPointIndices()
        if (indices && indices.length > 0) {
          const ids = await graph.value.getPointIdsByIndices(indices)
          if (ids && ids.length > 0) {
            const clickedId = ids[0]
            const node = nodes.value.find(n => String(n.id) === String(clickedId))
            if (node) {
              const raw = node._raw || node
              hoveredNode.value = {
                id: node.id,
                label: raw.label || raw.name || node.id,
                type: raw.type || node.type,
                color: node.color,
                path: raw.path,
                chunks: raw.chunks || raw.chunk_count,
                fileSize: raw.file_size,
                content: raw.content,
              }
              // 将节点居中放大，10秒后适配视图
              try {
                graph.value.pause()
                const idxArr = await graph.value.getPointIndicesByIds([String(node.id)])
                const realIdx = idxArr && idxArr.length > 0 ? idxArr[0] : indices[0]
                setTimeout(() => {
                  graph.value.zoomToPoint(realIdx, 600, 90)
                  setTimeout(() => {
                    graph.value.unpause()
                  }, 800)
                }, 100)
                // 10秒后适配视图
                if (_previewFitTimer) clearTimeout(_previewFitTimer)
                _previewFitTimer = setTimeout(() => {
                  _previewFitTimer = null
                  try { graph.value.fitView(5000) } catch(e) {}
                }, 10000)
              } catch (e) { /* ignore */ }
            }
          }
        } else {
          hoveredNode.value = null
        }
      } catch (err) {
        console.warn('[Graph] click select error:', err)
      }
    })
    g.start()

    // 延迟 fitView 让模拟先跑几步
    setTimeout(() => {
      try { g.fitView() } catch (e) { /* ignore */ }
    }, 1500)

    // 保存完整 config，后续 setConfig 必须传完整对象
    graphFullConfig.value = {
      points: buildPoints(nodes.value),
      pointIdBy: 'id',
      pointIndexBy: 'index',
      pointLabelBy: 'label',
      pointColorBy: 'color',
      links: buildLinks(links.value, showLinks.value),
      linkSourceBy: 'source',
      linkTargetBy: 'target',
      linkSourceIndexBy: 'sourceIndex',
      linkTargetIndexBy: 'targetIndex',
      linkWidthStrategy: 'single',
      linkColorStrategy: 'single',
      enableSimulation: true,
      simulationRepulsion: simRepulsion.value,
      simulationGravity: simGravity.value,
      simulationFriction: simFriction.value,
      simulationDecay: simDecay.value,
      simulationLinkDistance: simLinkDistance.value,
      simulationLinkSpring: 1,
      backgroundColor: bgColor,
      pointDefaultColor: '#3B82F6',
      pointSizeRange: [sizeRangeMin.value, sizeRangeMax.value],
      linkDefaultColor: linkDefaultColor.value,
      linkDefaultWidth: linkWidth.value,
      showLabels: showLinks.value,
      pointLabelFontSize: pointLabelFontSize.value,
      showDynamicLabels: showDynamicLabels.value,
      showTopLabels: showTopLabels.value,
      showTopLabelsLimit: showTopLabelsLimit.value,
      showHoveredPointLabel: true,
      pointLabelColor: pointLabelColor.value,
      selectPointOnClick: 'single',
      enableDrag: true,
      focusPointOnClick: true,
      onPointMouseOver: (idx) => { try { graph.value?.setPinnedPoints([idx]) } catch(e) {} },
      onPointMouseOut: () => { try { graph.value?.setPinnedPoints([]) } catch(e) {} },
    }

    graph.value = g

    // 移除 Cosmograph attribution 水印
    const attr = container.querySelector('[class*="attribution"]')
    if (attr) attr.remove()

    console.log('[Graph] Cosmograph initialized')
  } catch (err) {
    console.error('[Graph] initGraph error:', err)
  }
}

// ── 脉冲动画（高亮+放大+增加漂浮力）──
let pulseTimer = null
let pulseRestoreTimer = null
async function pulseNode(nodeId) {
  if (!graph.value) return
  try {
    // 通过 ID 获取内部索引
    const idxArr = await graph.value.getPointIndicesByIds([String(nodeId)])
    if (!idxArr || idxArr.length === 0) return
    const realIdx = idxArr[0]

    // 选中节点（白色聚焦环）
    graph.value.selectPoints([realIdx], false)

    // 增加漂浮力：降低引力 + 减小摩擦 + 给模拟脉冲
    updateGraphConfig({
      simulationGravity: 0.05,
      simulationFriction: 0.5,
      simulationImpulse: 1,
    })

    // 2 秒后取消选中 + 恢复模拟 + 5秒缓慢适配视图
    if (pulseTimer) clearTimeout(pulseTimer)
    pulseTimer = setTimeout(() => {
      pulseTimer = null
      try {
        graph.value.selectPoints(null)
        // 先恢复模拟参数让节点稳定下来
        updateGraphConfig({
          simulationGravity: simGravity.value,
          simulationFriction: simFriction.value,
        })
        // 再缓慢适配视图
        graph.value.fitView(5000)
      } catch (e) { /* ignore */ }
    }, 2000)

    // 8 秒后给一个小脉冲 + 静默刷新
    if (pulseRestoreTimer) clearTimeout(pulseRestoreTimer)
    pulseRestoreTimer = setTimeout(() => {
      pulseRestoreTimer = null
      try {
        updateGraphConfig({ simulationImpulse: 0.3 })
      } catch (e) { /* ignore */ }
      loadData()
    }, 8000)
  } catch (e) {
    console.warn('[Graph] pulseNode error:', e)
  }
}

// ── 增量更新图谱 ──
function updateGraphData() {
  if (!graph.value) return
  const pts = buildPoints(nodes.value)
  updateGraphConfig({ points: pts })
}

// ── 搜索 ──
async function handleSearch() {
  if (!searchQuery.value.trim()) {
    loadData()
    return
  }
  searching.value = true
  try {
    const result = await searchMemory(searchQuery.value)
    searchTime.value = result.search_ms

    const resultPaths = new Set(result.results.map(r => r.path))
    const pts = buildPoints(nodes.value).map(p => ({
      ...p,
      color: resultPaths.has(p._raw.path) ? '#ffffff' : p.color,
      size: resultPaths.has(p._raw.path) ? p.size * 1.5 : p.size,
    }))
    updateGraphConfig({ points: pts })
  } catch (err) {
    console.error('Search failed:', err)
  } finally {
    searching.value = false
  }
}

function debounceSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(handleSearch, 300)
}

function selectFile(file) {
  selectedFile.value = file.id
  const neighbors = new Set([String(file.id)])
  links.value.forEach(l => {
    const sid = String(l.source)
    const tid = String(l.target)
    if (sid === String(file.id)) neighbors.add(tid)
    if (tid === String(file.id)) neighbors.add(sid)
  })
  const pts = buildPoints(nodes.value).map(p => ({
    ...p,
    color: neighbors.has(p.id) ? '#ffffff' : p.color,
    size: p.id === String(file.id) ? p.size * 1.5 : p.size,
  }))
  updateGraphConfig({ points: pts })
}

function refreshData() {
  if (graph.value) {
    graph.value.destroy()
    graph.value = null
  }
  loadData()
}

// 销毁重建 Cosmograph（避免 removeChild bug）
function rebuildGraph() {
  if (graph.value) {
    graph.value.destroy()
    graph.value = null
  }
  nodes.value = [...nodes.value]
  initGraph()
}

function reheatSimulation() {
  if (graph.value) {
    try { graph.value.pause() } catch (e) { /* ignore */ }
    try { graph.value.unpause() } catch (e) { /* ignore */ }
  }
}

function simStart() {
  if (graph.value) {
    try { graph.value.start(1) } catch (e) { console.warn('[Graph] start failed:', e) }
  }
}

function simPause() {
  if (graph.value) {
    try { graph.value.pause() } catch (e) { console.warn('[Graph] pause failed:', e) }
  }
}

function simUnpause() {
  if (graph.value) {
    try { graph.value.unpause() } catch (e) { console.warn('[Graph] unpause failed:', e) }
  }
}

function fitToScreen() {
  if (graph.value) {
    graph.value.fitView()
  }
}

function getNodeConnections(nodeId) {
  let count = 0
  links.value.forEach(l => {
    if (String(l.source) === String(nodeId) || String(l.target) === String(nodeId)) count++
  })
  return count
}

function applyFilter() {
  const mc = minChunks.value
  const mconn = minConnections.value
  const connMap = {}
  links.value.forEach(l => {
    connMap[String(l.source)] = (connMap[String(l.source)] || 0) + 1
    connMap[String(l.target)] = (connMap[String(l.target)] || 0) + 1
  })

  const filteredNodes = nodes.value.filter(n => {
    return (n.chunks || 0) >= mc && (connMap[String(n.id)] || 0) >= mconn
  })
  const filteredIds = new Set(filteredNodes.map(n => String(n.id)))
  const filteredLinks = links.value.filter(l => filteredIds.has(String(l.source)) && filteredIds.has(String(l.target)))

  if (graph.value) {
    try {
      updateGraphConfig({ points: buildPoints(filteredNodes), links: buildLinks(filteredLinks, showLinks.value) })
    } catch (e) { console.warn('[Graph] filter failed:', e) }
  }
}

function resetFilter() {
  if (graph.value) {
    updateGraphConfig({ points: buildPoints(nodes.value), links: buildLinks(links.value, showLinks.value) })
  }
}

// ── Watch config changes ──

// 辅助函数：带完整映射的 setConfig（Cosmograph 要求每次传完整 config）
function updateGraphConfig(updates = {}) {
  if (!graph.value) return
  graphFullConfig.value = { ...graphFullConfig.value, ...updates }
  try {
    graph.value.setConfig(graphFullConfig.value)
  } catch (e) {
    console.warn('[Graph] setConfig failed:', e)
  }
}

// 外观 - 节点大小
watch([sizeRangeMin, sizeRangeMax], () => {
  updateGraphConfig({ pointSizeRange: [sizeRangeMin.value, sizeRangeMax.value] })
})

// 外观 - 连线开关
watch(showLinks, () => {
  updateGraphConfig({ linkDefaultWidth: showLinks.value ? linkWidth.value : 0 })
})

watch([linkWidth, linkDefaultColor], () => {
  updateGraphConfig({ linkDefaultWidth: showLinks.value ? linkWidth.value : 0, linkDefaultColor: linkDefaultColor.value })
})

// 标签
watch([showLabels, pointLabelFontSize, showDynamicLabels, showTopLabels, showTopLabelsLimit, pointLabelColor], () => {
  updateGraphConfig({
    showLabels: showLabels.value,
    pointLabelFontSize: pointLabelFontSize.value,
    showDynamicLabels: showDynamicLabels.value,
    showTopLabels: showTopLabels.value,
    showTopLabelsLimit: showTopLabelsLimit.value,
    pointLabelColor: pointLabelColor.value,
  })
})

// 模拟参数
watch([simRepulsion, simGravity, simFriction, simDecay, simLinkDistance], () => {
  updateGraphConfig({
    simulationRepulsion: simRepulsion.value,
    simulationGravity: simGravity.value,
    simulationFriction: simFriction.value,
    simulationDecay: simDecay.value,
    simulationLinkDistance: simLinkDistance.value,
  })
})

// ── Mouse move for tooltip ──
function handleKeyDown(e) {
  if (e.ctrlKey && e.key === 'x') {
    e.preventDefault()
    rightCollapsed.value = !rightCollapsed.value
    sidebarOpen.value = !rightCollapsed.value
  }
}

function handleMouseMove(e) {
  if (tooltip.value) {
    tooltipStyle.value = {
      left: e.clientX + 16 + 'px',
      top: e.clientY + 16 + 'px',
    }
  }
}

// ── 版本检查 ──
async function checkVersion() {
  try {
    const data = await getVersion()
    if (!currentVersion.value) {
      currentVersion.value = data.frontend || 'unknown'
    } else if (data.frontend && data.frontend !== currentVersion.value) {
      hasUpdate.value = true
    }
  } catch (err) {
    console.error('Version check failed:', err)
  }
}

function handleUpdate() {
  hasUpdate.value = false
  location.reload()
}

// ── Lifecycle ──
onMounted(() => {
  loadData()
  document.addEventListener('mousemove', handleMouseMove)
  document.addEventListener('keydown', handleKeyDown)

  // 自动刷新 watcher
  watch([autoRefresh, refreshInterval], () => {
    if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
    if (autoRefresh.value) {
      refreshTimer = setInterval(() => loadData(), refreshInterval.value)
    }
  }, { immediate: true })

  // 版本检查
  checkVersion()
  versionCheckTimer = setInterval(checkVersion, 30000)

  // WebSocket 连接
  function connectActivityWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/graphWs`

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      console.log('Activity WebSocket connected')
      if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer)
        wsReconnectTimer = null
      }
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'activity') {
          const path = data.path
          const matchNode = nodes.value.find(n => {
            const raw = n._raw || n
            return raw.path === path
          })
          if (matchNode) {
            pulseNode(matchNode.id)
          } else {
            loadData()
          }
        }
      } catch (e) {
        console.error('WebSocket message error:', e)
      }
    }

    ws.onclose = () => {
      console.log('Activity WebSocket closed, reconnecting in 3s...')
      wsReconnectTimer = setTimeout(connectActivityWebSocket, 3000)
    }

    ws.onerror = (err) => {
      console.error('Activity WebSocket error:', err)
    }
  }

  connectActivityWebSocket()
})

onUnmounted(() => {
  document.removeEventListener('mousemove', handleMouseMove)
  document.removeEventListener('keydown', handleKeyDown)
  if (refreshTimer) clearInterval(refreshTimer)
  if (versionCheckTimer) clearInterval(versionCheckTimer)
  if (ws) { ws.close(); ws = null }
  if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null }
  if (graph.value) graph.value.destroy()
})
</script>

<style scoped>
/* ===== CSS Custom Properties / Theming ===== */
.app {
  --bg: #0A0A0C;
  --bg-card: #141416;
  --bg-header: #111113;
  --bg-hover: #1A1A1E;
  --bg-input: #1A1A1E;
  --border: rgba(255, 255, 255, 0.06);
  --border-hover: rgba(255, 255, 255, 0.12);
  --text: #EDEDEF;
  --text-secondary: #8E8E93;
  --text-tertiary: #5A5A5E;
  --accent: #8B5CF6;
  --accent-hover: #7C3AED;
  --accent-subtle: rgba(139, 92, 246, 0.12);
  --blue: #3B82F6;
  --green: #10B981;
  --yellow: #F59E0B;
  --scrollbar-track: #0A0A0C;
  --scrollbar-thumb: #2A2A2E;

  width: 100vw;
  height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  font-size: 13px;
  line-height: 1.5;
  display: flex;
  flex-direction: column;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Light theme overrides */
.app.theme-dark {
  --bg: #0A0A0C;
  --bg-card: #141416;
  --bg-header: #111113;
  --bg-hover: #1A1A1E;
  --bg-input: #1A1A1E;
  --border: rgba(255, 255, 255, 0.06);
  --border-hover: rgba(255, 255, 255, 0.12);
  --text: #EDEDEF;
  --text-secondary: #8E8E93;
  --text-tertiary: #5A5A5E;
  --accent: #8B5CF6;
  --accent-hover: #7C3AED;
  --accent-subtle: rgba(139, 92, 246, 0.12);
  --scrollbar-track: #0A0A0C;
  --scrollbar-thumb: #2A2A2E;
}

.app:not(.theme-dark) {
  --bg: #F7F6F3;
  --bg-card: #FFFFFF;
  --bg-header: #EDEDEC;
  --bg-hover: #F0EFED;
  --bg-input: #F0EFED;
  --border: rgba(0, 0, 0, 0.06);
  --border-hover: rgba(0, 0, 0, 0.12);
  --text: #1A1F36;
  --text-secondary: #6B7280;
  --text-tertiary: #9CA3AF;
  --accent: #8B5CF6;
  --accent-hover: #7C3AED;
  --accent-subtle: rgba(139, 92, 246, 0.08);
  --scrollbar-track: #F7F6F3;
  --scrollbar-thumb: #D4D4D8;
}

/* ===== Header ===== */
.header {
  height: 48px;
  background: var(--bg-header);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  z-index: 100;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo {
  color: var(--accent);
  display: flex;
  align-items: center;
}

.project-info {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.project-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  cursor: pointer;
  transition: color 0.15s;
}
.project-name:hover { color: var(--accent); }

.project-version {
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: 'Inter', monospace;
}

.project-input {
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 4px 8px;
  color: var(--text);
  font-size: 13px;
  outline: none;
  font-family: inherit;
}
.project-input:focus { border-color: var(--accent); }

.header-center {
  display: flex;
  gap: 20px;
}

.stat {
  font-size: 12px;
  color: var(--text-secondary);
}
.stat-value {
  font-weight: 600;
  color: var(--text);
  margin-right: 2px;
}
.stat-time {
  color: var(--green);
  font-family: 'Inter', monospace;
  font-size: 11px;
}

.header-right {
  display: flex;
  gap: 4px;
  align-items: center;
}

/* ===== Buttons ===== */
.header-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  transition: all 0.15s;
  font-family: inherit;
  white-space: nowrap;
}
.header-btn:hover {
  color: var(--text);
  background: var(--bg-hover);
}

.btn-primary {
  background: var(--accent);
  color: #fff;
}
.btn-primary:hover {
  background: var(--accent-hover);
  color: #fff;
}

.btn-lang {
  background: var(--bg-input);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  font-weight: 600;
  min-width: 32px;
  justify-content: center;
  padding: 5px 8px;
}
.btn-lang:hover { color: var(--text); border-color: var(--border-hover); }

.btn-update {
  background: var(--yellow);
  color: #fff;
  animation: pulse-anim 2s infinite;
}
.btn-update:hover { background: #D97706; color: #fff; }
@keyframes pulse-anim {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.75; }
}

.btn-ghost {
  background: var(--bg-input);
  color: var(--text-secondary);
  border: 1px solid var(--border);
}
.btn-ghost:hover {
  color: var(--text);
  border-color: var(--border-hover);
  background: var(--bg-hover);
}

.theme-toggle {
  padding: 5px;
}
.sidebar-toggle {
  display: none;
}

.btn-icon {
  background: none;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  transition: color 0.15s;
}
.btn-icon:hover { color: var(--text); }

/* ===== Main Layout ===== */
.main {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* ===== Sidebars ===== */
.sidebar-left, .sidebar-right {
  width: 260px;
  min-width: 260px;
  max-width: 260px;
  background: var(--bg-card);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  transition: width 0.2s, min-width 0.2s, max-width 0.2s;
  flex-shrink: 0;
}
.sidebar-right {
  border-right: none;
  border-left: 1px solid var(--border);
}
.sidebar-left.collapsed {
  width: 40px;
  min-width: 40px;
  max-width: 40px;
}
.sidebar-right.collapsed {
  width: 0;
  min-width: 0;
  max-width: 0;
  overflow: hidden;
  border-left: none;
}
.sidebar-left.collapsed .panel-header h3 { display: none; }

.panel-header {
  height: 40px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.panel-header h3 {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

/* ===== Search ===== */
.search-box {
  margin-bottom: 16px;
}
.search-input-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0 10px;
  transition: border-color 0.15s;
}
.search-input-wrap:focus-within {
  border-color: var(--accent);
}
.search-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
}
.search-input {
  flex: 1;
  background: transparent;
  border: none;
  padding: 8px 0;
  color: var(--text);
  font-size: 12px;
  outline: none;
  font-family: inherit;
}
.search-input::placeholder {
  color: var(--text-tertiary);
}

/* ===== Sections ===== */
.section {
  margin-bottom: 8px;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  user-select: none;
  transition: color 0.15s;
}
.section-header:hover { color: var(--text); }
.section-count {
  color: var(--text-tertiary);
  font-weight: 400;
  margin-left: 4px;
}

/* ===== File List ===== */
.file-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12px;
  transition: background 0.15s;
}
.file-item:hover, .file-item.active {
  background: var(--accent-subtle);
}
.file-item.active .file-name {
  color: var(--accent);
}
.file-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.file-name {
  flex: 1;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-chunks {
  color: var(--text-tertiary);
  font-size: 11px;
  font-family: 'Inter', monospace;
  flex-shrink: 0;
}

/* ===== Config Groups ===== */
.config-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.config-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.config-item label {
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 500;
}

/* ===== Toggle Switch ===== */
.config-switch {
  -webkit-appearance: none;
  appearance: none;
  width: 32px;
  height: 18px;
  background: var(--bg-hover);
  border-radius: 9px;
  position: relative;
  cursor: pointer;
  transition: background 0.2s;
  outline: none;
  flex-shrink: 0;
  border: 1px solid var(--border);
}
.config-switch::after {
  content: '';
  position: absolute;
  width: 12px;
  height: 12px;
  background: var(--text-tertiary);
  border-radius: 50%;
  top: 2px;
  left: 2px;
  transition: all 0.2s;
}
.config-switch:checked {
  background: var(--accent);
  border-color: var(--accent);
}
.config-switch:checked::after {
  background: #fff;
  left: 16px;
}

/* ===== Range Slider ===== */
.config-range {
  width: 100%;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--bg-hover);
  border-radius: 2px;
  outline: none;
}
.config-range::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  background: var(--accent);
  border-radius: 50%;
  cursor: pointer;
  border: 2px solid var(--bg-card);
  box-shadow: 0 0 0 1px var(--accent);
}
.range-value {
  font-size: 11px;
  color: var(--text-tertiary);
  text-align: right;
  font-family: 'Inter', monospace;
}

/* ===== Graph Area ===== */
.graph-area {
  flex: 1;
  min-width: 0;
  position: relative;
  overflow: hidden;
}
.graph-container {
  width: 100%;
  height: 100%;
  position: relative;
}
/* 隐藏 Cosmograph attribution */
[class*="attribution"] {
  opacity: 0 !important;
  pointer-events: none !important;
  width: 0 !important;
  height: 0 !important;
  overflow: hidden !important;
}
.graph-container canvas {
  position: absolute;
  top: 0;
  left: 0;
}

/* ===== Tooltip ===== */
.tooltip {
  position: fixed;
  background: var(--bg-card);
  border: 1px solid var(--border-hover);
  border-radius: 8px;
  padding: 12px;
  max-width: 300px;
  font-size: 12px;
  line-height: 1.5;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  pointer-events: none;
  z-index: 1000;
  backdrop-filter: blur(12px);
}
.tip-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.tip-path { color: var(--blue); font-weight: 600; font-size: 12px; }
.tip-type {
  background: var(--bg-hover);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  color: var(--text-secondary);
}
.tip-meta { color: var(--text-tertiary); font-size: 11px; margin-bottom: 8px; }
.tip-content { color: var(--text-secondary); word-break: break-all; }

/* ===== Empty & Loading ===== */
.empty-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}
.loading-state {
  position: absolute;
  bottom: 20px;
  right: 20px;
  z-index: 10;
}
.empty-icon {
  color: var(--text-tertiary);
  opacity: 0.5;
}
.empty-text { color: var(--text-tertiary); font-size: 13px; }

.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ===== Preview Panel ===== */
.preview-panel { padding: 4px 0; }
.preview-card {
  background: var(--bg-input);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--border);
}
.preview-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 8px;
  word-break: break-all;
}
.preview-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
  font-size: 11px;
  color: var(--text-secondary);
}
.preview-badge {
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
  font-size: 10px;
  font-weight: 500;
}
.preview-path {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-bottom: 6px;
  word-break: break-all;
  font-family: 'Inter', monospace;
}
.preview-content {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.6;
  max-height: 80px;
  overflow: hidden;
  margin-bottom: 6px;
}
.preview-links {
  font-size: 11px;
  color: var(--blue);
}
.preview-links strong {
  color: var(--text-secondary);
}
.preview-empty {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 20px 0;
  text-align: center;
}

.btn-row {
  display: flex;
  gap: 4px;
  padding: 4px 0 8px;
}
.btn-row .header-btn {
  flex: 1;
  justify-content: center;
  font-size: 11px;
  padding: 5px 8px;
}

/* ===== Color Presets ===== */
.color-presets {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.color-swatch {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: all 0.15s;
}
.color-swatch:hover { transform: scale(1.1); }
.color-swatch.active {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-subtle);
}

/* ===== Dual Slider ===== */
.dual-slider {
  position: relative;
  height: 20px;
  display: flex;
  align-items: center;
}
.dual-range {
  position: absolute;
  width: 100%;
  pointer-events: none;
  background: transparent;
  z-index: 2;
}
.dual-range::-webkit-slider-thumb {
  pointer-events: all;
  position: relative;
  z-index: 3;
}

/* ===== Timeline ===== */
.timeline-container {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  padding: 8px 0;
  height: 120px;
  overflow-x: auto;
}
.timeline-bar-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  flex: 1;
  min-width: 32px;
  border-radius: 8px;
  padding: 4px 2px;
  transition: background 0.15s;
}
.timeline-bar-wrapper:hover { background: var(--accent-subtle); }
.timeline-bar-wrapper.active { background: var(--accent-subtle); }
.timeline-date {
  font-size: 9px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
  font-family: 'Inter', monospace;
}
.timeline-bar-bg {
  width: 16px;
  height: 60px;
  background: var(--bg-hover);
  border-radius: 3px;
  display: flex;
  align-items: flex-end;
  overflow: hidden;
}
.timeline-bar {
  width: 100%;
  border-radius: 3px;
  transition: height 0.3s ease;
  min-height: 2px;
}
.timeline-count {
  font-size: 9px;
  color: var(--text-tertiary);
  margin-top: 3px;
  font-family: 'Inter', monospace;
}
.timeline-info {
  margin-top: 8px;
  padding: 8px;
  background: var(--bg-input);
  border-radius: 8px;
  border: 1px solid var(--border);
}
.timeline-selected {
  font-size: 12px;
  color: var(--blue);
  margin-bottom: 6px;
  font-weight: 500;
}
.timeline-files {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.timeline-file-tag {
  font-size: 10px;
  padding: 2px 8px;
  background: var(--accent-subtle);
  color: var(--blue);
  border-radius: 4px;
}

/* ===== Floating Legend ===== */
.floating-legend {
  position: absolute;
  left: 12px;
  bottom: 12px;
  z-index: 10;
  font-size: 11px;
}
.legend-toggle {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
  font-size: 11px;
  font-weight: 500;
  backdrop-filter: blur(8px);
}
.legend-toggle:hover {
  background: var(--bg-hover);
  color: var(--text);
}
.legend-content {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  backdrop-filter: blur(8px);
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
}
.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.legend-line {
  width: 16px;
  height: 2px;
  background: rgba(100, 180, 255, 0.4);
  flex-shrink: 0;
  border-radius: 1px;
}

/* ===== Scrollbar ===== */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--scrollbar-track); }
::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 2px;
}
::-webkit-scrollbar-thumb:hover { background: var(--text-tertiary); }

/* ===== Responsive ===== */
@media (max-width: 767px) {
  .sidebar-toggle { display: flex; }
  .app { flex-direction: column; }
  .sidebar-right {
    position: fixed;
    top: 48px;
    right: 0;
    bottom: 0;
    z-index: 100;
    transform: translateX(100%);
    transition: transform 0.2s ease;
    max-width: 300px;
    width: 80vw;
    overflow-y: auto;
    box-shadow: -2px 0 12px rgba(0,0,0,0.2);
  }
  .sidebar-right.open { transform: translateX(0); }
  .sidebar-right.collapsed { transform: translateX(100%); }
  .graph-area { width: 100% !important; }
  .header { flex-wrap: wrap; gap: 4px; }
  .header-center { display: none; }
  .floating-legend { bottom: 8px; left: 8px; font-size: 10px; }
  .sidebar-left { width: 200px; min-width: 200px; max-width: 200px; }
}
</style>
