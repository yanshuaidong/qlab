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

    <div class="toolbar wind-toolbar">
      <h2>主力风向表</h2>
      <label class="wind-filter">
        <span class="toolbar-label">总市值大于等于</span>
        <el-input-number v-model="minMvYi" :min="0" :step="1" :precision="2" size="small"
          aria-label="总市值下限（亿元）" @change="loadWind" />
        <span class="toolbar-label">亿</span>
      </label>
      <label class="wind-filter">
        <el-switch v-model="dcOn" aria-label="启用东财超大单条件" @change="loadWind" />
        <span class="toolbar-label">东财超大单净流入占比大于等于</span>
        <el-input-number v-model="dcRate" :step="1" :precision="2" size="small" :disabled="!dcOn"
          aria-label="东财超大单净流入占比下限" @change="loadWind" />
        <span class="toolbar-label">%</span>
      </label>
      <label class="wind-filter">
        <el-switch v-model="thsOn" aria-label="启用同花顺大单条件" @change="loadWind" />
        <span class="toolbar-label">同花顺大单净流入占比大于等于</span>
        <el-input-number v-model="thsRate" :step="1" :precision="2" size="small" :disabled="!thsOn"
          aria-label="同花顺大单净流入占比下限" @change="loadWind" />
        <span class="toolbar-label">%</span>
      </label>
      <label class="wind-filter">
        <el-switch v-model="l2On" aria-label="启用 L2 主动超大单条件" @change="loadWind" />
        <span class="toolbar-label">L2主动超大单净流入占比大于等于</span>
        <el-input-number v-model="l2Rate" :step="1" :precision="2" size="small" :disabled="!l2On"
          aria-label="L2主动超大单净流入占比下限" @change="loadWind" />
        <span class="toolbar-label">%</span>
      </label>
    </div>
    <p class="hint">近一年逐日统计：先保留当天总市值达标的股票，再计入至少命中一个已开启净流入条件的股票。同一只股票当天只计 1 只。</p>
    <el-alert v-if="windError" :title="windError" type="error" :closable="false" show-icon />
    <div v-if="windData && anyFlowOn" class="limit-summary" aria-live="polite">
      <span>{{ windData.startDate }} 至 {{ windData.endDate }} · {{ windData.rows.length }} 个行情日</span>
      <span v-if="latestWind">区间最新：{{ latestWind.date }} · {{ latestWind.count }} 只</span>
    </div>
    <div class="chart-wrap limit-chart" v-loading="windLoading">
      <VChart v-if="anyFlowOn && windData?.rows.length" :option="windChartOption" autoresize @click="selectWindDay" />
      <el-empty v-else-if="!windLoading" :description="windEmptyDescription" />
    </div>
    <p class="hint methodology">统计口径：总市值取当日 daily_basic.total_mv，默认大于等于 400 亿。东财用超大单净流入占比，同花顺用大单净流入占比，L2 主动用超大单净流入占比，默认都大于等于 20%。开关关闭的条件不参与。占比为空或低于门槛不算命中。横轴只展示有行情的日期。点击柱子查看当日入选股票之后的涨幅。</p>

    <div v-if="selectedDate" ref="outcomeRef" class="outcome-section">
      <h2>{{ selectedDate }} 入选股票后续表现</h2>
      <p class="hint">以该日收盘为起点，3／5／10／15／20 日是该股之后第 N 个有收盘价的交易日。涨幅＝后续收盘 ÷ 信号日收盘 − 1。后续行情不足的不计入胜率和平均、中位涨幅。胜率为涨幅大于 0 的股票占有效样本的比例。</p>
      <el-alert v-if="outcomeError" :title="outcomeError" type="error" :closable="false" show-icon />
      <h3>总结</h3>
      <el-table :data="outcome?.summary || []" v-loading="outcomeLoading" empty-text="当日没有入选股票">
        <el-table-column prop="days" label="区间" width="90"><template #default="{ row }">{{ row.days }} 日</template></el-table-column>
        <el-table-column prop="sample" label="有效样本" width="100" />
        <el-table-column prop="wins" label="上涨只数" width="100" />
        <el-table-column label="胜率" width="100"><template #default="{ row }">{{ formatPercent(row.winRate) }}</template></el-table-column>
        <el-table-column label="平均涨幅" width="110"><template #default="{ row }"><span :class="pctClass(row.avg)">{{ formatSigned(row.avg) }}</span></template></el-table-column>
        <el-table-column label="中位涨幅" width="110"><template #default="{ row }"><span :class="pctClass(row.median)">{{ formatSigned(row.median) }}</span></template></el-table-column>
      </el-table>
      <h3>明细 · {{ outcome?.count ?? 0 }} 只</h3>
      <el-table :data="sortedStocks" v-loading="outcomeLoading" empty-text="当日没有入选股票"
        :default-sort="{ prop: '20', order: 'descending' }" @sort-change="onOutcomeSort">
        <el-table-column prop="tsCode" label="代码" width="120" />
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column v-for="day in horizons" :key="day" :prop="String(day)" :label="`${day}日涨幅`" min-width="110"
          sortable="custom" align="right">
          <template #default="{ row }"><span :class="pctClass(row.returns[day])">{{ formatSigned(row.returns[day]) }}</span></template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { getJson } from '../api.js'
import { createLimitChartOption, createMainForceChartOption } from '../utils/limit-chart.js'

const endDate = ref('')
const data = ref(null)
const loading = ref(false)
const error = ref('')
const minMvYi = ref(400)
const dcOn = ref(true)
const dcRate = ref(20)
const thsOn = ref(true)
const thsRate = ref(20)
const l2On = ref(true)
const l2Rate = ref(20)
const windData = ref(null)
const windLoading = ref(false)
const windError = ref('')
const selectedDate = ref('')
const outcome = ref(null)
const outcomeLoading = ref(false)
const outcomeError = ref('')
const outcomeSort = ref({ prop: '20', order: 'descending' })
const outcomeRef = ref(null)
const horizons = [3, 5, 10, 15, 20]
let requestId = 0
let controller
let windRequestId = 0
let windController
let outcomeRequestId = 0
let outcomeController

const latestRow = computed(() => data.value?.rows.at(-1))
const hasEstimates = computed(() => data.value?.rows.some(row => row.eligibleStocks > 0))
const chartOption = computed(() => createLimitChartOption(data.value?.rows || []))
const anyFlowOn = computed(() => dcOn.value || thsOn.value || l2On.value)
const latestWind = computed(() => windData.value?.rows.at(-1))
const windChartOption = computed(() => createMainForceChartOption(windData.value?.rows || []))
const emptyDescription = computed(() => {
  if (error.value) return '数据加载失败，请点击刷新重试'
  if (data.value?.rows.length) return '该时间段有行情，但没有可参与估算的股票'
  return '该时间段暂无日线行情，请更换截止日期或点击“最新一年”'
})
const windEmptyDescription = computed(() => {
  if (!anyFlowOn.value) return '请至少开启一个主力占比条件'
  if (windError.value) return '数据加载失败，请调整筛选或点击刷新重试'
  return '该时间段暂无日线行情，请更换截止日期或点击“最新一年”'
})
const sortedStocks = computed(() => {
  const stocks = outcome.value?.stocks || []
  const prop = outcomeSort.value.prop
  const order = outcomeSort.value.order
  const day = Number(prop)
  if (!horizons.includes(day) || !order) return stocks
  const direction = order === 'ascending' ? 1 : -1
  return [...stocks].sort((a, b) => {
    const av = a.returns[day]
    const bv = b.returns[day]
    if (av == null && bv == null) return a.tsCode < b.tsCode ? -1 : 1
    if (av == null) return 1
    if (bv == null) return -1
    return (av - bv) * direction || (a.tsCode < b.tsCode ? -1 : 1)
  })
})

function formatPercent(value) {
  return value == null ? '—' : `${value.toFixed(2)}%`
}

function formatSigned(value) {
  if (value == null) return '—'
  const text = `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
  return text
}

function pctClass(value) {
  if (value == null || value === 0) return ''
  return value > 0 ? 'up' : 'down'
}

function onOutcomeSort({ prop, order }) {
  outcomeSort.value = order ? { prop, order } : { prop: '20', order: 'descending' }
}

async function load() {
  const id = ++requestId
  controller?.abort()
  controller = new AbortController()
  const requestedDate = endDate.value
  loading.value = true
  error.value = ''
  data.value = null
  loadWind()
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

function finiteOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

async function loadWind() {
  const id = ++windRequestId
  windController?.abort()
  windController = new AbortController()
  if (!anyFlowOn.value) {
    windData.value = null
    windError.value = ''
    windLoading.value = false
    selectedDate.value = ''
    outcome.value = null
    outcomeError.value = ''
    return
  }
  const mv = finiteOrNull(minMvYi.value)
  const rates = {
    dcRate: finiteOrNull(dcRate.value),
    thsRate: finiteOrNull(thsRate.value),
    l2Rate: finiteOrNull(l2Rate.value),
  }
  if (mv == null || mv < 0 || (dcOn.value && rates.dcRate == null)
      || (thsOn.value && rates.thsRate == null) || (l2On.value && rates.l2Rate == null)) {
    windError.value = '市值和占比门槛必须是有限数字，市值不能为负'
    windLoading.value = false
    return
  }
  windLoading.value = true
  windError.value = ''
  try {
    const params = new URLSearchParams({
      minMvYi: String(mv),
      dc: dcOn.value ? '1' : '0',
      dcRate: String(rates.dcRate ?? 20),
      ths: thsOn.value ? '1' : '0',
      thsRate: String(rates.thsRate ?? 20),
      l2: l2On.value ? '1' : '0',
      l2Rate: String(rates.l2Rate ?? 20),
    })
    if (endDate.value) params.set('endDate', endDate.value)
    const result = await getJson(`/api/limit-analysis/main-force?${params}`, { signal: windController.signal })
    if (id !== windRequestId) return
    windData.value = result
    if (selectedDate.value) loadOutcomes()
  } catch (err) {
    if (id === windRequestId) windError.value = err.message
  } finally {
    if (id === windRequestId) windLoading.value = false
  }
}

async function selectWindDay(event) {
  if (event.componentType !== 'series' || event.seriesType !== 'bar') return
  const row = windData.value?.rows[event.dataIndex]
  if (!row) return
  selectedDate.value = row.date
  await loadOutcomes()
  await nextTick()
  outcomeRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function loadOutcomes() {
  const id = ++outcomeRequestId
  outcomeController?.abort()
  outcomeController = new AbortController()
  if (!selectedDate.value || !anyFlowOn.value) {
    outcome.value = null
    outcomeError.value = ''
    outcomeLoading.value = false
    return
  }
  const mv = finiteOrNull(minMvYi.value)
  const rates = {
    dcRate: finiteOrNull(dcRate.value),
    thsRate: finiteOrNull(thsRate.value),
    l2Rate: finiteOrNull(l2Rate.value),
  }
  if (mv == null || mv < 0) return
  outcomeLoading.value = true
  outcomeError.value = ''
  try {
    const params = new URLSearchParams({
      date: selectedDate.value,
      minMvYi: String(mv),
      dc: dcOn.value ? '1' : '0',
      dcRate: String(rates.dcRate ?? 20),
      ths: thsOn.value ? '1' : '0',
      thsRate: String(rates.thsRate ?? 20),
      l2: l2On.value ? '1' : '0',
      l2Rate: String(rates.l2Rate ?? 20),
    })
    const result = await getJson(`/api/limit-analysis/main-force/outcomes?${params}`, { signal: outcomeController.signal })
    if (id !== outcomeRequestId) return
    outcome.value = result
  } catch (err) {
    if (id === outcomeRequestId) outcomeError.value = err.message
  } finally {
    if (id === outcomeRequestId) outcomeLoading.value = false
  }
}

function resetToLatest() {
  endDate.value = ''
  load()
}

onMounted(load)
onBeforeUnmount(() => {
  requestId++
  windRequestId++
  outcomeRequestId++
  controller?.abort()
  windController?.abort()
  outcomeController?.abort()
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
h2 { margin: 0; font-size: 16px; }
.wind-toolbar { margin-top: 8px; }
.wind-filter { display: inline-flex; align-items: center; gap: 6px; }
h3 { margin: 8px 0 0; font-size: 14px; }
.outcome-section { display: flex; flex-direction: column; gap: 8px; }
</style>
