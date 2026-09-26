<template>
  <section class="page block-trade-page">
    <div class="toolbar">
      <h1>大宗交易</h1>
      <span class="hint">已入库成交 · 逐笔统计</span>
      <el-button class="refresh" :loading="overviewLoading || stocksLoading || stockLoading" @click="refresh">刷新数据</el-button>
    </div>
    <el-tabs v-model="activeTab" class="block-tabs">
      <el-tab-pane label="全局看" name="overview" />
      <el-tab-pane label="具体看" name="stock" />
    </el-tabs>

    <template v-if="activeTab === 'overview'">
      <el-alert v-if="overviewError" :title="overviewError" type="error" :closable="false" show-icon />
      <div v-if="overview?.summary" class="summary-grid" aria-live="polite">
        <div class="stat"><span>大宗交易总笔数</span><strong>{{ formatNumber(overview.summary.count, 0) }}</strong></div>
        <div class="stat"><span>涉及证券</span><strong>{{ formatNumber(overview.summary.stock_count, 0) }} <small>只</small></strong></div>
        <div class="stat"><span>有成交的交易日</span><strong>{{ formatNumber(overview.summary.day_count, 0) }} <small>天</small></strong></div>
        <div class="stat range"><span>已入库日期范围</span><strong>{{ overview.summary.start_date || '—' }} ～ {{ overview.summary.end_date || '—' }}</strong></div>
      </div>
      <div class="panel">
        <div class="panel-heading"><h2>每日大宗交易数量</h2><span class="hint">悬停查看数量 · 滚轮或底部滑块缩放时间</span></div>
        <div class="overview-chart" v-loading="overviewLoading">
          <VChart v-if="overview?.rows.length && !overviewError" :option="overviewOption" autoresize />
          <el-empty v-else-if="!overviewLoading" :description="overviewError ? '数据加载失败，请点击刷新重试' : '暂无已入库的大宗交易数据'" />
        </div>
      </div>
      <p class="hint">数量按成交明细的笔数统计，同一证券同日多笔成交分别计数，不是股票只数。横轴仅展示已入库的成交日期，未采集或无记录的日期不补零；范围以库内数据为准。</p>
    </template>

    <template v-else>
      <el-alert v-if="stocksError" :title="stocksError" type="error" :closable="false" show-icon />
      <div class="toolbar stock-toolbar">
        <label class="mv-filter">
          <span class="toolbar-label">总市值小于</span>
          <el-input-number v-model="maxMvYi" :min="0" :step="10" size="small" :value-on-clear="null"
            aria-label="总市值上限（亿元）" @change="onMaxMvChange" />
          <span class="toolbar-label">亿</span>
        </label>
        <div class="trade-filters">
          <label class="trade-filter">
            <el-switch v-model="amountOn" aria-label="启用单笔金额筛选" @change="onTradeFilterChange" />
            <span class="toolbar-label">单笔金额</span>
            <span class="toolbar-label">大于等于</span>
            <el-input-number v-model="minAmountWan" :min="0" :step="100" size="small" :disabled="!amountOn"
              :value-on-clear="null" aria-label="单笔金额下限（万元）" @change="onTradeFilterChange" />
            <span class="toolbar-label">万</span>
            <span class="toolbar-label">小于等于</span>
            <el-input-number v-model="maxAmountWan" :min="0" :step="100" size="small" :disabled="!amountOn"
              :value-on-clear="null" aria-label="单笔金额上限（万元）" @change="onTradeFilterChange" />
            <span class="toolbar-label">万</span>
          </label>
          <label class="trade-filter">
            <el-switch v-model="discountOn" aria-label="启用折价率筛选" @change="onTradeFilterChange" />
            <span class="toolbar-label">折价率</span>
            <span class="toolbar-label">大于</span>
            <el-input-number v-model="minDiscount" :step="0.5" :precision="2" size="small" :disabled="!discountOn"
              :value-on-clear="null" aria-label="折价率下限（%）" @change="onTradeFilterChange" />
            <span class="toolbar-label">%</span>
            <span class="toolbar-label">小于</span>
            <el-input-number v-model="maxDiscount" :step="0.5" :precision="2" size="small" :disabled="!discountOn"
              :value-on-clear="null" aria-label="折价率上限（%）" @change="onTradeFilterChange" />
            <span class="toolbar-label">%</span>
          </label>
        </div>
        <div class="stock-nav">
          <el-button size="small" :disabled="!canPrev" @click="goStock(-1)">上一个</el-button>
          <el-select-v2 id="block-stock-select" v-model="selectedCode" :options="stockOptions" filterable
            :loading="stocksLoading" class="stock-select" placeholder="代码或名称"
            aria-label="选择有过大宗交易的股票" no-match-text="没有匹配的大宗交易证券" no-data-text="暂无大宗交易证券" />
          <el-button size="small" :disabled="!canNext" @click="goStock(1)">下一个</el-button>
          <span v-if="stockIndex >= 0" class="hint stock-pos">{{ stockIndex + 1 }} / {{ stocks.length }}</span>
        </div>
        <span class="hint">{{ stockListHint }}</span>
      </div>
      <el-alert v-if="stockError" :title="stockError" type="error" :closable="false" show-icon>
        <el-button size="small" @click="loadStock">重试个股数据</el-button>
      </el-alert>
      <div v-loading="stockLoading" class="stock-body">
        <template v-if="stockData && !stockError">
          <div class="stock-summary">
            <h2>{{ selectedStock?.name || '名称暂无' }} <span class="hint">{{ selectedCode }}</span></h2>
            <span>{{ Number.isFinite(selectedStock?.total_mv) ? `总市值 ${formatMv(selectedStock.total_mv)}` : '市值未知' }}</span>
            <span>{{ stockData.rows.length }} 笔{{ tradeFilterActive ? '符合筛选的' : '' }}成交 · {{ model.byDate.size }} 个成交日</span>
            <span class="hint">行情截至 {{ lastDailyDate || '暂无行情' }} · 大宗交易截至 {{ eventDates[0] || '—' }}</span>
          </div>
          <el-alert v-if="model.missingDates.length" type="warning" :closable="false" show-icon
            :title="`${model.missingDates.length} 个大宗成交日缺少有效 K 线，已保留在下方成交笔数图及日期列表中，不补造 K 线。缺少当日收盘价时折溢价显示为无法计算。`" />
          <div class="panel kline-panel">
            <div class="panel-heading">
              <h2>{{ model.dailyByDate.size ? '未复权日 K 线 · 大宗交易标注' : '大宗交易笔数 · 暂无 K 线行情' }}</h2>
              <div class="chart-actions">
                <el-checkbox v-model="showLabels">显示折溢价文字</el-checkbox>
                <el-radio-group v-model="viewMode" size="small" aria-label="K线查看范围" @change="applyView">
                  <el-radio-button value="all">查看全部</el-radio-button>
                  <el-radio-button value="date">定位所在日期</el-radio-button>
                </el-radio-group>
              </div>
            </div>
            <div class="marker-legend">
              <span class="premium">▼ 溢价</span><span class="discount">▲ 折价</span>
              <span class="flat">● 平价</span><span class="unknown">● 无法计算</span>
              <span class="mixed">紫色成交柱：同日存在多种折溢价类型</span>
            </div>
            <div class="candle-info" aria-live="polite">
              <span>{{ hoverDate || selectedDate || '移入图表查看当日数据' }}</span>
              <template v-if="hoverCandle">
                <span>开 {{ formatPrice(hoverCandle.open) }}</span><span>高 {{ formatPrice(hoverCandle.high) }}</span>
                <span>低 {{ formatPrice(hoverCandle.low) }}</span><span>收 {{ formatPrice(hoverCandle.close) }}</span>
                <span :class="pctClass(hoverCandle.pct_chg)">涨跌 {{ formatSignedPercent(hoverCandle.pct_chg) }}</span>
              </template>
              <span>大宗 {{ hoverTrades.length }} 笔</span>
              <span v-if="hoverTrades.length">{{ hoverPremiumSummary }}</span>
            </div>
            <p class="hint chart-guide">{{ model.dailyByDate.size ? '上图看价格与折溢价标注，下图看大宗交易笔数；点击任一天 K 线或成交柱，下方表格展示该日全部明细。' : '当前仅有成交记录，暂无可绘制的 K 线；点击成交柱或选择日期查看当日明细。' }}</p>
            <div class="block-kline-stage">
              <ChartPane v-if="model.dates.length" ref="chartRef" :series="klineSeries" :pane-stretch="model.dailyByDate.size ? [4, 1] : [1]"
                :fit-token="selectedCode" @ready="applyView" @hover="onHover" @click="selectChartDay" />
              <el-empty v-else description="暂无行情或成交数据" />
            </div>
          </div>
          <p class="hint methodology">折溢价率 =（大宗成交价 ÷ 同日未复权收盘价 − 1）× 100%。正值为溢价、负值为折价。图上同日同类成交合并标注笔数和折溢价范围，表格逐笔保留；该指标不是相对昨收价的涨跌幅。</p>
          <div class="panel detail-panel">
            <div class="panel-heading">
              <h2>成交明细 <span class="hint">{{ selectedDate || '请选择日期' }} · {{ selectedTrades.length }} 笔</span></h2>
              <el-select v-model="selectedDate" class="date-select" aria-label="选择大宗成交日期" placeholder="选择成交日期" @change="onSelectedDateChange">
                <el-option v-if="selectedDate && !model.byDate.has(selectedDate)" :label="`${selectedDate} · 无大宗交易`" :value="selectedDate" />
                <el-option v-for="date in eventDates" :key="date" :value="date"
                  :label="`${date} · ${model.byDate.get(date).length} 笔${model.dailyByDate.has(date) ? '' : ' · 缺 K 线'}`" />
              </el-select>
            </div>
            <el-table :data="pagedTrades" :row-key="rowKey" stripe :max-height="440"
              :empty-text="selectedDate ? '该日期没有符合筛选的大宗交易记录' : '点击 K 线或选择成交日期查看明细'">
              <el-table-column prop="record_no" label="当日序号" width="90" />
              <el-table-column prop="trade_date" label="成交日期" width="115" />
              <el-table-column prop="ts_code" label="代码" width="110" />
              <el-table-column label="成交价" width="100" align="right"><template #default="{ row }">{{ formatNumber(row.price, 6) }}</template></el-table-column>
              <el-table-column label="当日收盘价" width="110" align="right"><template #default="{ row }">{{ formatPrice(row.close) }}</template></el-table-column>
              <el-table-column label="折溢价" width="140" align="right"><template #default="{ row }"><span :class="premiumKind(row.premium_rate)">{{ premiumLabel(row.premium_rate) }}</span></template></el-table-column>
              <el-table-column label="成交量（万股）" width="140" align="right"><template #default="{ row }">{{ formatNumber(row.vol, 4) }}</template></el-table-column>
              <el-table-column label="成交金额（万元）" width="155" align="right"><template #default="{ row }">{{ formatNumber(row.amount, 4) }}</template></el-table-column>
              <el-table-column prop="buyer" label="买方营业部" min-width="240" show-overflow-tooltip />
              <el-table-column prop="seller" label="卖方营业部" min-width="240" show-overflow-tooltip />
            </el-table>
            <div class="table-footer">
              <span class="hint">相同明细也逐笔保留。成交金额单位为万元。折价率相对当日未复权收盘价；筛选开启后，缺少收盘价或成交价的记录不计入。</span>
              <el-pagination v-if="selectedTrades.length > pageSize" v-model:current-page="detailPage" :page-size="pageSize"
                :total="selectedTrades.length" layout="prev, pager, next, total" small />
            </div>
          </div>
        </template>
        <el-empty v-else-if="!stockLoading && !stockError" :description="emptyStockText" />
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ChartPane from '../components/ChartPane.vue'
import { formatNumber, formatPrice, formatSignedPercent, getJson, pctClass, toTradeDate } from '../api.js'
import { buildBlockTradeKline, createBlockOverviewOption, premiumKind, premiumLabel } from '../utils/block-trade-chart.js'

const activeTab = ref('overview')
const overview = ref(null)
const overviewLoading = ref(false)
const overviewError = ref('')
const stocks = ref([])
const stocksLoading = ref(false)
const stocksError = ref('')
const DEFAULT_MAX_MV_YI = 100
const selectedCode = ref('')
const maxMvYi = ref(DEFAULT_MAX_MV_YI)
const amountOn = ref(true)
const minAmountWan = ref(2000)
const maxAmountWan = ref(null)
const discountOn = ref(true)
const minDiscount = ref(3)
const maxDiscount = ref(8)
const mvAvailable = ref(true)
const viewMode = ref('all')
const stockData = ref(null)
const stockLoading = ref(false)
const stockError = ref('')
const selectedDate = ref('')
const hoverDate = ref('')
const showLabels = ref(true)
const chartRef = ref(null)
const detailPage = ref(1)
const pageSize = 20
let overviewController, stocksController, stockController

const overviewOption = computed(() => createBlockOverviewOption(overview.value?.rows || []))
const stockOptions = computed(() => stocks.value.map(stock => ({ value: stock.ts_code,
  label: `${stock.ts_code} ${stock.name || '名称暂无'} · ${formatMv(stock.total_mv)} · ${stock.count} 笔`,
})))
const stockIndex = computed(() => stocks.value.findIndex(stock => stock.ts_code === selectedCode.value))
const canPrev = computed(() => stockIndex.value > 0 && !stocksLoading.value)
const canNext = computed(() => stockIndex.value >= 0 && stockIndex.value < stocks.value.length - 1 && !stocksLoading.value)
const tradeFilterText = computed(() => {
  const parts = []
  if (amountOn.value) {
    const bits = []
    if (minAmountWan.value != null) bits.push(`大于等于 ${minAmountWan.value} 万`)
    if (maxAmountWan.value != null) bits.push(`小于等于 ${maxAmountWan.value} 万`)
    parts.push(bits.length ? `单笔金额${bits.join('、')}` : '单笔金额不限')
  }
  if (discountOn.value) {
    const bits = []
    if (minDiscount.value != null) bits.push(`大于 ${minDiscount.value}%`)
    if (maxDiscount.value != null) bits.push(`小于 ${maxDiscount.value}%`)
    parts.push(bits.length ? `折价率${bits.join('、')}` : '折价率不限')
  }
  return parts.join('；')
})
const tradeFilterActive = computed(() => amountOn.value || discountOn.value)
const stockListHint = computed(() => {
  const count = `${stocks.value.length} 只`
  const trade = tradeFilterText.value ? `；${tradeFilterText.value}` : ''
  const omitted = tradeFilterActive.value ? '。没有市值或不满足成交条件的不列入；笔数为符合条件的成交' : '；没有市值的不列入'
  if (!mvAvailable.value) return `共 ${count}有过大宗交易的证券；库内没有市值，未按市值筛选${trade}`
  if (maxMvYi.value == null) return `共 ${count}有过大宗交易的证券，不限市值${trade}；无名称时显示代码`
  return `共 ${count}，最新总市值小于 ${maxMvYi.value} 亿${trade}${omitted}`
})
const emptyStockText = computed(() => {
  if (stocks.value.length) return '请选择一只有过大宗交易的股票'
  if (tradeFilterText.value) return `没有同时满足市值和成交条件的证券（${tradeFilterText.value}）`
  if (maxMvYi.value == null) return '暂无大宗交易证券'
  return `没有总市值小于 ${maxMvYi.value} 亿的大宗交易证券`
})
const selectedStock = computed(() => stocks.value.find(stock => stock.ts_code === selectedCode.value))
const model = computed(() => buildBlockTradeKline(stockData.value?.daily || [], stockData.value?.rows || [], showLabels.value))
const eventDates = computed(() => [...model.value.byDate.keys()].sort().reverse())
const lastDailyDate = computed(() => [...model.value.dailyByDate.keys()].sort().at(-1))
const selectedTrades = computed(() => model.value.byDate.get(selectedDate.value) || [])
const pagedTrades = computed(() => selectedTrades.value.slice((detailPage.value - 1) * pageSize, detailPage.value * pageSize))
const hoverCandle = computed(() => model.value.dailyByDate.get(hoverDate.value || selectedDate.value))
const hoverTrades = computed(() => model.value.byDate.get(hoverDate.value || selectedDate.value) || [])
const hoverPremiumSummary = computed(() => {
  const counts = { premium: 0, discount: 0, flat: 0, unknown: 0 }
  hoverTrades.value.forEach(row => counts[premiumKind(row.premium_rate)]++)
  return `溢价 ${counts.premium} / 折价 ${counts.discount} / 平价 ${counts.flat} / 未知 ${counts.unknown}`
})
const klineSeries = computed(() => {
  const hasCandles = model.value.dailyByDate.size > 0
  const candles = hasCandles ? [{ id: 'block-candles', type: 'candlestick', data: model.value.candles,
    options: { upColor: '#fd4432', downColor: '#2fa331', wickUpColor: '#fd4432', wickDownColor: '#2fa331',
      borderVisible: false, priceLineVisible: false, priceFormat: { type: 'price', precision: 2, minMove: 0.01 } },
    priceScale: { scaleMargins: { top: 0.20, bottom: 0.20 } }, markers: model.value.markers,
  }] : []
  return [...candles, { id: 'block-count', type: 'histogram', data: model.value.histogram, paneIndex: hasCandles ? 1 : 0,
    options: { priceLineVisible: false, lastValueVisible: false,
      priceFormat: { type: 'custom', minMove: 1, formatter: value => `${Math.round(value)} 笔` } },
    priceScale: { scaleMargins: { top: 0.12, bottom: 0 } },
  }]
})

function rowKey(row) { return `${row.trade_date}-${row.record_no}` }
function formatMv(totalMvWan) {
  if (!Number.isFinite(totalMvWan)) return '市值未知'
  const yi = totalMvWan / 10000
  const text = yi >= 100 ? String(Math.round(yi)) : yi.toFixed(2).replace(/\.?0+$/, '')
  return `${text} 亿`
}
function onHover(event) { hoverDate.value = toTradeDate(event?.time) }
function selectChartDay(event) {
  const date = toTradeDate(event?.time)
  if (!date) return
  selectedDate.value = date
  hoverDate.value = ''
  if (viewMode.value === 'date') focusSelected()
}
function onSelectedDateChange() {
  if (viewMode.value === 'date') focusSelected()
}
async function focusSelected() {
  await nextTick()
  const index = model.value.dates.indexOf(selectedDate.value)
  if (index < 0) return
  chartRef.value?.getChart()?.timeScale().setVisibleLogicalRange({ from: Math.max(-1, index - 45), to: Math.min(model.value.dates.length + 2, index + 25) })
}
function showAll() { chartRef.value?.getChart()?.timeScale().fitContent() }
function applyView() {
  if (viewMode.value === 'date') focusSelected()
  else showAll()
}
function goStock(delta) {
  const next = stocks.value[stockIndex.value + delta]
  if (next) selectedCode.value = next.ts_code
}
function normalizeMaxMvYi(value) {
  if (value == null || value === '') return null
  const n = Number(value)
  if (!Number.isFinite(n) || n < 0) return DEFAULT_MAX_MV_YI
  return n
}
function onMaxMvChange() {
  maxMvYi.value = normalizeMaxMvYi(maxMvYi.value)
  loadStocks()
}
function normalizeOptional(value, { min = null } = {}) {
  if (value == null || value === '') return null
  const n = Number(value)
  if (!Number.isFinite(n) || (min != null && n < min)) return null
  return n
}
function tradeFilterError() {
  minAmountWan.value = normalizeOptional(minAmountWan.value, { min: 0 })
  maxAmountWan.value = normalizeOptional(maxAmountWan.value, { min: 0 })
  minDiscount.value = normalizeOptional(minDiscount.value)
  maxDiscount.value = normalizeOptional(maxDiscount.value)
  if (amountOn.value && minAmountWan.value != null && maxAmountWan.value != null && minAmountWan.value > maxAmountWan.value) {
    return '单笔金额的大于等于不能高于小于等于'
  }
  if (discountOn.value && minDiscount.value != null && maxDiscount.value != null && minDiscount.value >= maxDiscount.value) {
    return '折价率下限必须小于上限'
  }
  return ''
}
function appendTradeFilters(params) {
  if (amountOn.value) {
    if (minAmountWan.value != null) params.set('minAmountWan', String(minAmountWan.value))
    if (maxAmountWan.value != null) params.set('maxAmountWan', String(maxAmountWan.value))
  }
  if (discountOn.value) {
    if (minDiscount.value != null) params.set('minDiscount', String(minDiscount.value))
    if (maxDiscount.value != null) params.set('maxDiscount', String(maxDiscount.value))
  }
}
async function onTradeFilterChange() {
  const message = tradeFilterError()
  if (message) {
    stocksError.value = message
    return
  }
  const previous = selectedCode.value
  await loadStocks()
  if (selectedCode.value && selectedCode.value === previous) loadStock()
}
async function loadOverview() {
  overviewController?.abort()
  const request = new AbortController()
  overviewController = request
  overviewLoading.value = true
  overviewError.value = ''
  try {
    const result = await getJson('/api/block-trade/overview', { signal: request.signal })
    if (!request.signal.aborted) overview.value = result
  } catch (err) {
    if (!request.signal.aborted) { overviewError.value = err.message; overview.value = null }
  } finally { if (!request.signal.aborted) overviewLoading.value = false }
}
async function loadStocks() {
  stocksController?.abort()
  const request = new AbortController()
  stocksController = request
  stocksLoading.value = true
  stocksError.value = ''
  try {
    const message = tradeFilterError()
    if (message) {
      stocksError.value = message
      stocksLoading.value = false
      return
    }
    const params = new URLSearchParams()
    if (maxMvYi.value != null) params.set('maxMvYi', String(maxMvYi.value))
    appendTradeFilters(params)
    const result = await getJson(`/api/block-trade/stocks?${params}`, { signal: request.signal })
    if (request.signal.aborted) return
    mvAvailable.value = result.mv_available !== false
    stocks.value = result.items || []
    if (!stocks.value.some(row => row.ts_code === selectedCode.value)) {
      selectedCode.value = (stocks.value.find(row => row.name) || stocks.value[0])?.ts_code || ''
    }
  } catch (err) { if (!request.signal.aborted) stocksError.value = err.message }
  finally { if (!request.signal.aborted) stocksLoading.value = false }
}
async function loadStock() {
  stockController?.abort()
  const request = new AbortController()
  stockController = request
  stockData.value = null
  stockError.value = ''
  selectedDate.value = ''
  hoverDate.value = ''
  stockLoading.value = false
  if (!selectedCode.value) return
  stockLoading.value = true
  try {
    const params = new URLSearchParams()
    appendTradeFilters(params)
    const query = params.toString()
    const result = await getJson(`/api/block-trade/stock/${encodeURIComponent(selectedCode.value)}${query ? `?${query}` : ''}`, { signal: request.signal })
    if (request.signal.aborted) return
    stockData.value = result
    selectedDate.value = eventDates.value[0] || ''
  } catch (err) { if (!request.signal.aborted) stockError.value = err.message }
  finally { if (!request.signal.aborted) stockLoading.value = false }
}
function refresh() { loadOverview(); loadStocks(); if (selectedCode.value) loadStock() }
watch(selectedCode, loadStock)
watch(selectedDate, () => { detailPage.value = 1 })
onMounted(() => { loadOverview(); loadStocks() })
onBeforeUnmount(() => { overviewController?.abort(); stocksController?.abort(); stockController?.abort() })
</script>

<style scoped>
.block-trade-page { overflow-y: auto; display: block; padding: 18px 22px 28px; }
h1 { font-size: 21px; margin: 0; font-weight: 650; }
h2 { font-size: 15px; margin: 0; font-weight: 600; }
p { margin: 12px 0; line-height: 1.7; }
.refresh { margin-left: auto; }
.block-tabs { margin-top: 12px; }
.block-tabs :deep(.el-tabs__content) { display: none; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(120px, 1fr)) minmax(280px, 1.5fr); gap: 12px; margin: 8px 0 18px; }
.stat { padding: 16px; background: #161c25; border: 1px solid var(--border); border-radius: 8px; }
.stat > span { display: block; color: var(--text-dim); font-size: 12px; margin-bottom: 10px; }
.stat strong { font-size: 25px; font-weight: 600; font-variant-numeric: tabular-nums; }
.stat small { font-size: 12px; color: var(--text-dim); }
.stat.range strong { font-size: 14px; line-height: 30px; }
.panel { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.panel-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; }
.overview-chart { height: max(380px, 52vh); }
.stock-toolbar { margin-bottom: 16px; }
.mv-filter, .trade-filter { display: inline-flex; align-items: center; gap: 8px; }
.mv-filter :deep(.el-input-number) { width: 118px; }
.trade-filters { display: flex; flex-wrap: wrap; gap: 8px 16px; flex: 1 1 100%; }
.trade-filter :deep(.el-input-number) { width: 118px; }
.stock-nav { display: flex; align-items: center; gap: 8px; flex: 1 1 480px; min-width: min(100%, 320px); }
.stock-select { flex: 1; width: auto; min-width: 180px; }
.stock-pos { font-variant-numeric: tabular-nums; white-space: nowrap; }
.stock-body { min-height: 260px; }
.stock-summary { display: flex; align-items: center; flex-wrap: wrap; gap: 12px 24px; margin-bottom: 14px; font-size: 13px; }
.stock-summary h2 { font-size: 18px; }
.kline-panel { margin-top: 14px; }
.chart-actions { display: flex; align-items: center; gap: 12px; }
.chart-actions :deep(.el-radio-button__inner) { padding: 5px 12px; }
.marker-legend { display: flex; flex-wrap: wrap; gap: 16px; padding: 0 16px; font-size: 12px; }
.premium { color: #fd4432; } .discount { color: #2fa331; } .flat { color: #e5bf65; } .unknown { color: #8b95a8; } .mixed { color: #be8cf0; }
.candle-info { display: flex; flex-wrap: wrap; gap: 6px 14px; min-height: 34px; margin: 12px 16px 0; font-size: 12px; font-variant-numeric: tabular-nums; }
.chart-guide { padding: 0 16px; margin: 0 0 8px; }
.block-kline-stage { height: 460px; }
.methodology { margin: 12px 0 18px; }
.date-select { width: 290px; max-width: 100%; }
.table-footer { display: flex; justify-content: space-between; flex-wrap: wrap; align-items: center; gap: 12px; padding: 12px 16px; }
.detail-panel { margin-bottom: 14px; }
.el-alert { margin: 10px 0; }
@media (max-width: 1100px) { .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .block-trade-page { padding: 12px; } .summary-grid { grid-template-columns: 1fr; } .chart-actions { flex-wrap: wrap; } }
</style>
