<template>
  <section class="page signal-analysis-page">
    <div class="toolbar">
      <h1>信号分析</h1>
      <el-radio-group v-model="group" aria-label="信号类型">
        <el-radio-button value="total">全部信号</el-radio-button>
        <el-radio-button value="correct">仅好信号</el-radio-button>
        <el-radio-button value="fail">仅差信号</el-radio-button>
      </el-radio-group>
      <span class="toolbar-label">截止日期</span>
      <el-date-picker v-model="endDate" type="date" value-format="YYYY-MM-DD"
        format="YYYY-MM-DD" :clearable="false" aria-label="统计截止日期" @change="load" />
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>
    <p class="hint">按所有股票的信号发生日期统计，每条标记计 1 次；连续 365 个自然日（含截止日），无信号的日期为 0。好／差信号对应 K 线正确点／失败点。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-if="data" class="analysis-summary" aria-live="polite">
      <span>{{ data.startDate }} 至 {{ data.endDate }} · 共 {{ data.days }} 天</span>
      <span>{{ selected.label }}：<strong>{{ total }}</strong> 次</span>
      <span>有信号的日期：<strong>{{ activeDays }}</strong> 天</span>
      <span>单日最多：<strong>{{ peak }}</strong> 次</span>
    </div>
    <div class="chart-wrap signal-chart" v-loading="loading">
      <VChart v-if="data" :option="chartOption" :update-options="{ replaceMerge: ['series'] }" autoresize @click="selectDay" />
      <div v-if="data && total === 0 && !loading" class="empty-notice">该时间段内暂无{{ selected.label }}，每日次数均为 0</div>
      <el-empty v-if="!data && !loading" :description="error ? '数据加载失败，请点击刷新重试' : '暂无信号数据'" />
    </div>
    <p class="hint">点击柱子，在下方查看当天对应的股票及已标记信号日期的 K 线。</p>
    <div v-if="selectedDate" ref="detailsRef" class="signal-details-section">
      <SignalDayStocks :date="selectedDate" :group="group" />
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { getJson } from '../api.js'
import SignalDayStocks from '../components/SignalDayStocks.vue'

const groups = {
  total: { label: '全部信号', color: '#5b9fd6' },
  correct: { label: '好信号', color: '#ffd54f' },
  fail: { label: '差信号', color: '#ff3dce' },
}
const group = ref('total')
const endDate = ref('')
const data = ref(null)
const loading = ref(false)
const error = ref('')
const selectedDate = ref('')
const detailsRef = ref(null)
let requestId = 0

async function selectDay(event) {
  if (event.componentType !== 'series' || event.seriesType !== 'bar' || loading.value) return
  const row = data.value?.rows[event.dataIndex]
  if (!row || row[group.value] === 0) return
  selectedDate.value = row.date
  await nextTick()
  detailsRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
const selected = computed(() => groups[group.value])
const values = computed(() => (data.value?.rows || []).map(row => row[group.value]))
const total = computed(() => values.value.reduce((sum, count) => sum + count, 0))
const activeDays = computed(() => values.value.filter(count => count > 0).length)
const peak = computed(() => Math.max(0, ...values.value))
const chartOption = computed(() => ({
  backgroundColor: 'transparent',
  animationDuration: 250,
  grid: { left: 66, right: 30, top: 58, bottom: 90 },
  legend: {
    top: 8,
    data: (group.value === 'total' ? ['correct', 'fail'] : [group.value]).map(key => groups[key].label),
    selectedMode: false,
  },
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    valueFormatter: value => `${value} 次`,
  },
  xAxis: {
    type: 'category',
    name: '日期',
    nameLocation: 'middle',
    nameGap: 32,
    data: (data.value?.rows || []).map(row => row.date),
    axisLabel: { formatter: value => value.slice(5), hideOverlap: true },
    axisLine: { lineStyle: { color: '#8b95a8' } },
  },
  yAxis: {
    type: 'value',
    name: '信号发生次数（次）',
    min: 0,
    minInterval: 1,
    max: peak.value === 0 ? 1 : undefined,
    splitLine: { lineStyle: { color: '#243044' } },
  },
  dataZoom: [
    { type: 'inside', start: 0, end: 100 },
    { type: 'slider', bottom: 12, height: 22, start: 0, end: 100, borderColor: '#243044' },
  ],
  // ECharts 按系列顺序从下往上堆叠：好信号在下，差信号在上。
  series: (group.value === 'total' ? ['correct', 'fail'] : [group.value]).map(key => ({
    id: key,
    name: groups[key].label,
    type: 'bar',
    stack: group.value === 'total' ? 'signals' : undefined,
    data: (data.value?.rows || []).map(row => ({
      value: row[key],
      itemStyle: row.date === selectedDate.value
        ? { color: groups[key].color, borderColor: '#ffffff', borderWidth: 1 }
        : undefined,
    })),
    itemStyle: { color: groups[key].color },
    barMaxWidth: 22,
    emphasis: { itemStyle: { opacity: 0.8 } },
  })),
}))

async function load() {
  const id = ++requestId
  const requestedDate = endDate.value
  loading.value = true
  error.value = ''
  data.value = null
  selectedDate.value = ''
  try {
    const query = requestedDate ? `?${new URLSearchParams({ endDate: requestedDate })}` : ''
    const result = await getJson(`/api/signal-analysis${query}`)
    if (id !== requestId) return
    data.value = result
    endDate.value = result.endDate
  } catch (err) {
    if (id === requestId) error.value = err.message
  } finally {
    if (id === requestId) loading.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => { requestId++ })
</script>

<style scoped>
.signal-analysis-page { overflow: auto; }
h1 { margin: 0 12px 0 0; font-size: 18px; }
.hint { margin: 0; line-height: 1.7; }
.analysis-summary { display: flex; flex-wrap: wrap; gap: 12px 24px; font-size: 13px; color: var(--text-dim); }
.analysis-summary strong { color: var(--text); font-variant-numeric: tabular-nums; }
.signal-analysis-page > * { flex-shrink: 0; }
.signal-chart { position: relative; flex: 0 0 clamp(360px, 55vh, 560px); min-height: 360px; }
.signal-details-section { scroll-margin-top: 12px; }
.empty-notice { position: absolute; top: 18px; left: 0; right: 0; text-align: center; font-size: 13px; color: var(--text-dim); pointer-events: none; }
</style>
