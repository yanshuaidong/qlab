<template>
  <section class="page kline-page">
    <div class="chart-wrap kline-stage">
      <ChartPane
        :series="chartSeries"
        :price-scales="priceScales"
        :pane-stretch="paneStretch"
        :fit-token="fitToken"
        @click="onChartClick"
        @hover="onChartHover"
      />
      <div class="kline-overlays" :style="overlayGridStyle">
        <div class="overlay-pane overlay-sub overlay-main">
          <div class="pane-heading">
            <span class="pane-title" :class="{ 'is-error': !!error }">
              {{ error || stockTitle }}
              <span v-if="!error && marketCapText" class="pane-mv">{{ marketCapText }}</span>
            </span>
            <button
              type="button"
              class="kline-nav-btn"
              :disabled="!canSwitchStock"
              @click="goNeighbor(-1)"
            >
              上一个
            </button>
            <button
              type="button"
              class="kline-nav-btn"
              :disabled="!canSwitchStock"
              @click="goNeighbor(1)"
            >
              下一个
            </button>
          </div>
          <div v-if="hoverStats" class="kline-legend">
            <span>{{ hoverStats.date }}</span>
            <span>开 <b>{{ hoverStats.open }}</b></span>
            <span>高 <b>{{ hoverStats.high }}</b></span>
            <span>低 <b>{{ hoverStats.low }}</b></span>
            <span :class="hoverStats.cls">
              收 <b>{{ hoverStats.close }}</b>
            </span>
            <span :class="hoverStats.cls">
              {{ hoverStats.change }} {{ hoverStats.pct }}
            </span>
            <span>振幅 {{ hoverStats.amp }}</span>
            <span>量 {{ hoverStats.vol }}</span>
            <span>额 {{ hoverStats.amount }}</span>
          </div>
          <div class="pane-metric kline-stock-tools">
            <label class="kline-mv-filter">
              <span>大于</span>
              <el-input
                v-model="minMvYi"
                class="kline-mv-input"
                size="small"
                type="number"
                min="0"
                step="any"
                @change="onMinMvChange"
              />
              <span>亿</span>
            </label>
            <el-select-v2
              v-model="selectedCode"
              class="kline-search"
              size="small"
              filterable
              :options="stockOptions"
              :teleported="true"
              placeholder="搜索或下拉选股"
              popper-class="kline-stock-popper"
              @change="onStockChange"
            >
              <template #default="{ item }">
                <div class="stock-option">
                  <span class="code">{{ item.ts_code }}</span>
                  <span>{{ item.name }}</span>
                </div>
              </template>
            </el-select-v2>
          </div>
        </div>
        <div
          v-for="pane in subPanes"
          :key="pane.id"
          class="overlay-pane overlay-sub"
        >
          <span class="pane-title">
            {{ pane.title }}
            <span
              v-if="subHover[pane.id]"
              class="pane-hover-value"
              :class="subHover[pane.id].cls"
            >
              {{ subHover[pane.id].text }}
            </span>
          </span>
          <el-select
            v-if="pane.fields"
            v-model="metrics[pane.id]"
            class="pane-metric"
            size="small"
            filterable
            :teleported="true"
          >
            <el-option
              v-for="field in pane.fields"
              :key="field.id"
              :label="field.label"
              :value="field.id"
            />
          </el-select>
        </div>
      </div>
    </div>
    <el-dialog
      v-model="markDialog.visible"
      title="标记"
      width="440px"
      append-to-body
      align-center
    >
      <p class="mark-date">交易日：{{ markDialog.tradeDate }}</p>
      <el-radio-group v-model="markDialog.markType">
        <el-radio value="correct">正确点</el-radio>
        <el-radio value="fail">失败点</el-radio>
      </el-radio-group>
      <el-input
        v-model="markDialog.reason"
        class="mark-reason"
        type="textarea"
        :rows="3"
        :placeholder="markReasonPlaceholder"
        maxlength="500"
        show-word-limit
      />
      <p v-if="markDialog.existing" class="hint mark-hint">
        当前已标记为「{{ markTypeLabel(markDialog.existing.mark_type) }}」，可改类型、原因或删除。
      </p>
      <template #footer>
        <el-button
          v-if="markDialog.existing"
          type="danger"
          plain
          :loading="markDialog.saving"
          @click="removeMark"
        >
          删除
        </el-button>
        <el-button @click="markDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="markDialog.saving" @click="saveMark">
          确定
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import ChartPane from '../components/ChartPane.vue'
import {
  debounce,
  flowColor,
  formatAmount,
  formatMarketCapYi,
  formatPercent,
  formatPrice,
  formatSigned,
  formatSignedPercent,
  formatVolume,
  getJson,
  pctClass,
  sendJson,
  toTradeDate,
} from '../api.js'

const DEFAULT_MIN_MV_YI = 1

const DC_FIELDS = [
  { id: 'net_amount', label: '主力净流入额(万元)', kind: 'amount' },
  { id: 'net_amount_rate', label: '主力净流入占比(%)', kind: 'percent' },
  { id: 'buy_elg_amount', label: '超大单净流入额(万元)', kind: 'amount' },
  { id: 'buy_elg_amount_rate', label: '超大单净流入占比(%)', kind: 'percent' },
  { id: 'buy_lg_amount', label: '今日大单净流入额(万元)', kind: 'amount' },
  { id: 'buy_lg_amount_rate', label: '今日大单净流入占比(%)', kind: 'percent' },
  { id: 'buy_md_amount', label: '今日中单净流入额(万元)', kind: 'amount' },
  { id: 'buy_md_amount_rate', label: '今日中单净流入占比(%)', kind: 'percent' },
  { id: 'buy_sm_amount', label: '今日小单净流入额(万元)', kind: 'amount' },
  { id: 'buy_sm_amount_rate', label: '今日小单净流入占比(%)', kind: 'percent' },
]

const THS_FIELDS = [
  { id: 'net_amount', label: '资金净流入(万元)', kind: 'amount' },
  { id: 'net_d5_amount', label: '5日主力净额(万元)', kind: 'amount' },
  { id: 'buy_lg_amount', label: '今日大单净流入额(万元)', kind: 'amount' },
  { id: 'buy_lg_amount_rate', label: '今日大单净流入占比(%)', kind: 'percent' },
  { id: 'buy_md_amount', label: '今日中单净流入额(万元)', kind: 'amount' },
  { id: 'buy_md_amount_rate', label: '今日中单净流入占比(%)', kind: 'percent' },
  { id: 'buy_sm_amount', label: '今日小单净流入额(万元)', kind: 'amount' },
  { id: 'buy_sm_amount_rate', label: '今日小单净流入占比(%)', kind: 'percent' },
]

const L2_FIELDS = [
  { id: 'net_amount', label: '主力净流入额(万元)', kind: 'amount' },
  { id: 'net_amount_rate', label: '主力净流入占比(%)', kind: 'percent' },
  { id: 'mf_net_amount', label: '主动买卖净流入(万元)', kind: 'amount' },
  { id: 'mf_net_amount_rate', label: '主动买卖净流入占比(%)', kind: 'percent' },
  { id: 'buy_elg_amount', label: '超大单净流入额(万元)', kind: 'amount' },
  { id: 'buy_elg_amount_rate', label: '超大单净流入占比(%)', kind: 'percent' },
  { id: 'buy_lg_amount', label: '今日大单净流入额(万元)', kind: 'amount' },
  { id: 'buy_lg_amount_rate', label: '今日大单净流入占比(%)', kind: 'percent' },
  { id: 'buy_md_amount', label: '今日中单净流入额(万元)', kind: 'amount' },
  { id: 'buy_md_amount_rate', label: '今日中单净流入占比(%)', kind: 'percent' },
  { id: 'buy_sm_amount', label: '今日小单净流入额(万元)', kind: 'amount' },
  { id: 'buy_sm_amount_rate', label: '今日小单净流入占比(%)', kind: 'percent' },
]

const paneStretch = [3.2, 0.85, 1, 1, 1]
const overlayGridStyle = {
  gridTemplateRows: paneStretch.map((n) => `${n}fr`).join(' '),
}

const selectedCode = ref('')
const minMvYi = ref(DEFAULT_MIN_MV_YI)
const stockOptions = ref([])
const stock = ref(null)
let defaultStock = null
let appliedMinMvYi = DEFAULT_MIN_MV_YI
const dailyRows = ref([])
const dcRows = ref([])
const thsRows = ref([])
const l2Rows = ref([])
const metrics = reactive({
  dc: 'net_amount',
  ths: 'net_amount',
  l2: 'net_amount',
})
const error = ref('')
const loading = ref(false)
const hoverDate = ref('')
const marks = ref([])
const markDialog = reactive({
  visible: false,
  tradeDate: '',
  markType: 'correct',
  reason: '',
  existing: null,
  saving: false,
})
let loadSeq = 0

const subPanes = [
  { id: 'volume', title: '成交量' },
  { id: 'dc', title: '东财', fields: DC_FIELDS },
  { id: 'ths', title: '同花顺', fields: THS_FIELDS },
  { id: 'l2', title: 'L2主动', fields: L2_FIELDS },
]

function toStockOption(item) {
  return {
    value: item.ts_code,
    label: `${item.ts_code} ${item.name || ''}`.trim(),
    ts_code: item.ts_code,
    name: item.name,
  }
}

const stockTitle = computed(() => {
  if (loading.value) return '加载中…'
  if (!stock.value) return '个股K线'
  return stock.value.name || stock.value.ts_code
})

const marketCapText = computed(() => {
  if (loading.value || !stock.value) return ''
  return formatMarketCapYi(stock.value.total_mv)
})

const canSwitchStock = computed(() => stockOptions.value.length > 1)

const fitToken = computed(() => {
  const code = stock.value?.ts_code || ''
  return `${code}:${dailyRows.value.length}`
})

function markTypeLabel(type) {
  return type === 'fail' ? '失败点' : '正确点'
}

const markReasonPlaceholder = computed(() =>
  markDialog.markType === 'fail' ? '失败的原因（可选）' : '正确的原因（可选）',
)

function candleMarkers() {
  return marks.value.map((item) => {
    const isCorrect = item.mark_type !== 'fail'
    return {
      id: String(item.id),
      time: item.trade_date,
      position: isCorrect ? 'belowBar' : 'aboveBar',
      shape: isCorrect ? 'arrowUp' : 'arrowDown',
      color: isCorrect ? '#26a69a' : '#ef5350',
      text: isCorrect ? '正' : '败',
      size: 1.25,
    }
  })
}

function fieldMeta(fields, id) {
  return fields.find((item) => item.id === id) || fields[0]
}

function indexRows(rows) {
  const map = Object.create(null)
  for (const row of rows) map[row.trade_date] = row
  return map
}

function amplitudePct(row) {
  if (row?.high == null || row?.low == null) return null
  const base = row.pre_close || row.open
  if (!base) return null
  return ((row.high - row.low) / base) * 100
}

const dailyByDate = computed(() => indexRows(dailyRows.value))
const dcByDate = computed(() => indexRows(dcRows.value))
const thsByDate = computed(() => indexRows(thsRows.value))
const l2ByDate = computed(() => indexRows(l2Rows.value))

const activeDaily = computed(() => {
  const rows = dailyRows.value
  if (!rows.length) return null
  return dailyByDate.value[hoverDate.value] || rows[rows.length - 1]
})

const hoverStats = computed(() => {
  const row = activeDaily.value
  if (!row) return null
  const change =
    row.change ??
    (row.close != null && row.pre_close != null ? row.close - row.pre_close : null)
  const pct =
    row.pct_chg ?? (row.pre_close ? (change / row.pre_close) * 100 : null)
  return {
    date: row.trade_date,
    open: formatPrice(row.open),
    high: formatPrice(row.high),
    low: formatPrice(row.low),
    close: formatPrice(row.close),
    change: formatSigned(change),
    pct: formatSignedPercent(pct),
    amp: formatPercent(amplitudePct(row)),
    vol: formatVolume(row.vol),
    amount: formatAmount(row.amount, '千元'),
    cls: pctClass(change ?? pct),
  }
})

const subHover = computed(() => {
  const date = activeDaily.value?.trade_date
  if (!date) return {}
  const flowPanes = [
    ['dc', DC_FIELDS, dcByDate.value],
    ['ths', THS_FIELDS, thsByDate.value],
    ['l2', L2_FIELDS, l2ByDate.value],
  ]
  const result = {
    volume: {
      text: formatVolume(activeDaily.value.vol),
      cls: pctClass(activeDaily.value.change ?? activeDaily.value.pct_chg),
    },
  }
  for (const [id, fields, byDate] of flowPanes) {
    const meta = fieldMeta(fields, metrics[id])
    const value = byDate[date]?.[meta.id]
    result[id] = {
      text:
        value == null
          ? '—'
          : meta.kind === 'percent'
            ? formatSignedPercent(value)
            : formatAmount(value, '万元'),
      cls: pctClass(value),
    }
  }
  return result
})

function flowSeries(id, paneIndex, rows, fieldId, fields) {
  const meta = fieldMeta(fields, fieldId)
  const formatter =
    meta.kind === 'percent'
      ? (value) => formatPercent(value)
      : (value) => formatAmount(value, '万元')
  return {
    id,
    type: 'histogram',
    paneIndex,
    data: rows.map((row) => ({
      time: row.trade_date,
      value: row[meta.id] ?? 0,
      color: flowColor(row[meta.id]),
    })),
    options: {
      lastValueVisible: false,
      priceLineVisible: false,
      priceFormat: { type: 'custom', formatter },
    },
    priceScale: { scaleMargins: { top: 0.12, bottom: 0.08 } },
  }
}

const chartSeries = computed(() => {
  const candles = dailyRows.value
    .filter((row) => row.open != null && row.close != null)
    .map((row) => ({
      time: row.trade_date,
      open: row.open,
      high: row.high,
      low: row.low,
      close: row.close,
    }))

  const volumes = dailyRows.value.map((row) => ({
    time: row.trade_date,
    value: row.vol ?? 0,
    color: (row.close ?? 0) >= (row.open ?? 0) ? '#ef535080' : '#26a69a80',
  }))

  return [
    {
      id: 'candle',
      type: 'candlestick',
      paneIndex: 0,
      data: candles,
      options: {
        upColor: '#ef5350',
        downColor: '#26a69a',
        borderVisible: false,
        wickUpColor: '#ef5350',
        wickDownColor: '#26a69a',
      },
      markers: candleMarkers(),
    },
    {
      id: 'volume',
      type: 'histogram',
      paneIndex: 1,
      data: volumes,
      options: {
        priceFormat: { type: 'volume' },
        lastValueVisible: false,
        priceLineVisible: false,
      },
      priceScale: { scaleMargins: { top: 0.12, bottom: 0 } },
    },
    flowSeries('flow-dc', 2, dcRows.value, metrics.dc, DC_FIELDS),
    flowSeries('flow-ths', 3, thsRows.value, metrics.ths, THS_FIELDS),
    flowSeries('flow-l2', 4, l2Rows.value, metrics.l2, L2_FIELDS),
  ]
})

const priceScales = {
  right: { scaleMargins: { top: 0.08, bottom: 0.04 } },
}

async function loadStock(item) {
  const seq = ++loadSeq
  stock.value = item
  hoverDate.value = ''
  markDialog.visible = false
  loading.value = true
  error.value = ''
  const code = encodeURIComponent(item.ts_code)
  try {
    const [daily, dc, ths, l2, markData, basic] = await Promise.all([
      getJson(`/api/daily/${code}`),
      getJson(`/api/moneyflow/${code}?source=dc`),
      getJson(`/api/moneyflow/${code}?source=ths`),
      getJson(`/api/moneyflow/${code}?source=l2`),
      getJson(`/api/marks/${code}`),
      getJson(`/api/daily-basic/${code}`).catch(() => ({ item: null })),
    ])
    if (seq !== loadSeq) return
    stock.value = { ...item, total_mv: basic.item?.total_mv ?? null }
    dailyRows.value = daily.rows || []
    dcRows.value = dc.rows || []
    thsRows.value = ths.rows || []
    l2Rows.value = l2.rows || []
    marks.value = markData.items || []
    if (!dailyRows.value.length) {
      error.value = '该代码没有日线数据'
    }
  } catch (err) {
    if (seq !== loadSeq) return
    error.value = err.message
    dailyRows.value = []
    dcRows.value = []
    thsRows.value = []
    l2Rows.value = []
    marks.value = []
    stock.value = { ...item, total_mv: null }
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

function normalizeMinMvYi(value) {
  if (value === '' || value == null) return DEFAULT_MIN_MV_YI
  const n = Number(value)
  if (!Number.isFinite(n) || n < 0) return DEFAULT_MIN_MV_YI
  return n
}

async function loadStockList(preferredCode) {
  const min = normalizeMinMvYi(minMvYi.value)
  minMvYi.value = min
  appliedMinMvYi = min
  const list = await getJson(`/api/stocks?minMvYi=${encodeURIComponent(min)}`)
  stockOptions.value = (list.items || []).map(toStockOption)
  if (!stockOptions.value.length) {
    selectedCode.value = ''
    stock.value = null
    dailyRows.value = []
    dcRows.value = []
    thsRows.value = []
    l2Rows.value = []
    marks.value = []
    error.value = `没有市值大于 ${min} 亿的股票`
    return
  }

  const preferred =
    preferredCode || selectedCode.value || defaultStock?.ts_code || ''
  const found =
    stockOptions.value.find((row) => row.value === preferred) ||
    (defaultStock &&
      stockOptions.value.find((row) => row.value === defaultStock.ts_code)) ||
    stockOptions.value[0]
  selectedCode.value = found.value
  if (stock.value?.ts_code !== found.value) {
    await loadStock(found)
  }
}

const onMinMvChange = debounce(() => {
  const min = normalizeMinMvYi(minMvYi.value)
  minMvYi.value = min
  if (min === appliedMinMvYi) return
  loadStockList().catch((err) => {
    error.value = err.message
  })
}, 400)

watch(minMvYi, () => {
  onMinMvChange()
})

function onStockChange(code) {
  if (!code) return
  const item = stockOptions.value.find((row) => row.value === code)
  if (item) loadStock(item)
}

function goNeighbor(delta) {
  const list = stockOptions.value
  if (list.length < 2) return
  let index = list.findIndex((row) => row.value === selectedCode.value)
  if (index < 0) index = 0
  const next = list[(index + delta + list.length) % list.length]
  selectedCode.value = next.value
  loadStock(next)
}

function onChartHover(payload) {
  const next = payload?.time ? toTradeDate(payload.time) : ''
  if (next !== hoverDate.value) hoverDate.value = next
}

function onChartClick(payload) {
  if (payload.paneIndex !== 0 || loading.value || !stock.value) return
  const tradeDate = toTradeDate(payload.time)
  if (!tradeDate) return
  if (!dailyRows.value.some((row) => row.trade_date === tradeDate)) return

  const existing =
    marks.value.find((item) => item.trade_date === tradeDate) || null
  markDialog.tradeDate = tradeDate
  markDialog.existing = existing
  markDialog.markType = existing ? existing.mark_type : 'correct'
  markDialog.reason = existing?.reason || ''
  markDialog.visible = true
}

async function saveMark() {
  if (!stock.value || markDialog.saving) return
  markDialog.saving = true
  try {
    const data = await sendJson('/api/marks', 'POST', {
      ts_code: stock.value.ts_code,
      trade_date: markDialog.tradeDate,
      mark_type: markDialog.markType,
      reason: markDialog.reason.trim(),
    })
    const item = data.item
    const index = marks.value.findIndex(
      (row) => row.trade_date === item.trade_date,
    )
    if (index >= 0) marks.value.splice(index, 1, item)
    else marks.value.push(item)
    markDialog.visible = false
    ElMessage.success(`已标记${markTypeLabel(item.mark_type)} ${item.trade_date}`)
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    markDialog.saving = false
  }
}

async function removeMark() {
  const existing = markDialog.existing
  if (!existing || markDialog.saving) return
  markDialog.saving = true
  try {
    await sendJson(`/api/marks/${existing.id}`, 'DELETE')
    marks.value = marks.value.filter((item) => item.id !== existing.id)
    markDialog.visible = false
    ElMessage.success(`已删除 ${existing.trade_date} 的标记`)
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    markDialog.saving = false
  }
}

onMounted(async () => {
  try {
    const meta = await getJson('/api/meta')
    defaultStock = meta.defaultStock || null
    await loadStockList(defaultStock?.ts_code)
  } catch (err) {
    error.value = err.message
  }
})
</script>
