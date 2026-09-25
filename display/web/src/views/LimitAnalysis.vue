<template>
  <section class="page limit-analysis-page">
    <div class="toolbar">
      <h1>涨停跌停</h1>
      <el-tag type="warning" effect="plain">收盘估算</el-tag>
      <span class="toolbar-label">截止日期</span>
      <el-date-picker v-model="endDate" type="date" value-format="YYYY-MM-DD"
        format="YYYY-MM-DD" :clearable="false" aria-label="统计截止日期" @change="load" />
      <el-button :loading="loading" @click="load">刷新</el-button>
      <el-button :disabled="loading" @click="resetToLatest">最新一年</el-button>
    </div>
    <p class="hint">近一年逐日统计：红柱向上为涨停数量，绿柱向下为跌停数量；悬停查看当日数量，拖动底部滑块或滚轮缩放日期。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-if="data" class="limit-summary" aria-live="polite">
      <span>{{ data.startDate }} 至 {{ data.endDate }} · {{ data.rows.length }} 个行情日</span>
      <template v-if="latestRow">
        <span>区间最新：{{ latestRow.date }}</span>
        <template v-if="latestRow.eligibleStocks > 0">
          <span>涨停 <strong class="up">{{ latestRow.up }}</strong> 只</span>
          <span>跌停 <strong class="down">{{ latestRow.down }}</strong> 只</span>
        </template>
        <span v-else>当日无可估算数据</span>
        <span>参与估算 {{ latestRow.eligibleStocks }} / {{ latestRow.totalStocks }} 只</span>
      </template>
    </div>
    <div class="chart-wrap limit-chart" v-loading="loading">
      <VChart v-if="hasEstimates" :option="chartOption" autoresize />
      <el-empty v-else-if="!loading" :description="emptyDescription" />
    </div>
    <p class="hint methodology">统计口径：基于库内未复权日线收盘价及前收盘价，按主板 10%、主板 ST 5%、创业板／科创板 20%、北交所 30% 推算涨跌停价（四舍五入至分）。ST 使用当日股票名称识别，主板缺少当日名称、停牌或价格无效的记录不参与估算。仅展示有行情的日期，缺失日期不补零。当前没有官方涨跌停价，无法准确识别新股无涨跌幅限制期、退市整理等特殊交易规则，结果仅供参考；盘中触板但收盘未封板不计入。</p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getJson } from '../api.js'
import { createLimitChartOption } from '../utils/limit-chart.js'

const endDate = ref('')
const data = ref(null)
const loading = ref(false)
const error = ref('')
let requestId = 0
let controller

const latestRow = computed(() => data.value?.rows.at(-1))
const hasEstimates = computed(() => data.value?.rows.some(row => row.eligibleStocks > 0))
const chartOption = computed(() => createLimitChartOption(data.value?.rows || []))
const emptyDescription = computed(() => {
  if (error.value) return '数据加载失败，请点击刷新重试'
  if (data.value?.rows.length) return '该时间段有行情，但没有可参与估算的股票'
  return '该时间段暂无日线行情，请更换截止日期或点击“最新一年”'
})

async function load() {
  const id = ++requestId
  controller?.abort()
  controller = new AbortController()
  const requestedDate = endDate.value
  loading.value = true
  error.value = ''
  data.value = null
  try {
    const query = requestedDate ? `?${new URLSearchParams({ endDate: requestedDate })}` : ''
    const result = await getJson(`/api/limit-analysis${query}`, { signal: controller.signal })
    if (id !== requestId) return
    data.value = result
    endDate.value = result.endDate
  } catch (err) {
    if (id === requestId) error.value = err.message
  } finally {
    if (id === requestId) loading.value = false
  }
}

function resetToLatest() {
  endDate.value = ''
  load()
}

onMounted(load)
onBeforeUnmount(() => {
  requestId++
  controller?.abort()
})
</script>

<style scoped>
.limit-analysis-page { overflow: auto; }
h1 { margin: 0 12px 0 0; font-size: 18px; }
.hint { margin: 0; line-height: 1.7; color: var(--text-dim); font-size: 13px; }
.limit-summary { display: flex; flex-wrap: wrap; gap: 12px 24px; font-size: 13px; color: var(--text-dim); }
.limit-summary strong { font-size: 18px; font-variant-numeric: tabular-nums; }
.limit-analysis-page > * { flex-shrink: 0; }
.limit-chart { flex: 1 0 420px; min-height: 420px; }
.methodology { font-size: 12px; }
</style>
