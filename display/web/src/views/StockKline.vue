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
          <div class="kline-main-meta">
          <div class="pane-heading">
            <span class="pane-title" :class="{ 'is-error': !!error }">
              <span>{{ error || stockTitle }}</span>
              <span v-if="!error && marketCapText" class="pane-mv">{{ marketCapText }}</span>
              <span v-if="!error && hoverStats" class="kline-legend">
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
              </span>
            </span>
          </div>
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
      <div class="kline-dock">
        <div class="kline-dock-bar">
          <el-select-v2
            v-model="selectedCode"
            class="kline-dock-stock"
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
          <button
            type="button"
            class="kline-dock-btn"
            :disabled="!canSwitchStock"
            @click="goNeighbor(-1)"
          >
            上一个
          </button>
          <button
            type="button"
            class="kline-dock-btn"
            :disabled="!canSwitchStock"
            @click="goNeighbor(1)"
          >
            下一个
          </button>
          <button
            type="button"
            class="kline-dock-btn"
            :class="{ 'is-on': settingsOpen }"
            :aria-pressed="settingsOpen"
            aria-controls="kline-settings-panel"
            @click="settingsOpen = !settingsOpen"
          >
            设置
          </button>
        </div>
        <div
          v-show="settingsOpen"
          id="kline-settings-panel"
          class="kline-dock-panel"
        >
          <article class="kline-filter-card" :class="{ 'is-off': !mvFilterEnabled }">
              <header class="kline-filter-card__head">
                <span class="kline-filter-card__name">最近日市值</span>
                <el-switch v-model="mvFilterEnabled" size="small" />
              </header>
              <div class="kline-filter-card__body">
                <label class="kline-filter-row">
                  <span>大于等于</span>
                  <el-input
                    v-model="minMvYi"
                    class="kline-mv-input"
                    size="small"
                    type="number"
                    min="0"
                    step="any"
                    :disabled="!mvFilterEnabled"
                  />
                  <span>亿</span>
                </label>
                <label class="kline-filter-row">
                  <span>小于等于</span>
                  <el-input
                    v-model="maxMvYi"
                    class="kline-mv-input"
                    size="small"
                    type="number"
                    min="0"
                    step="any"
                    :disabled="!mvFilterEnabled"
                  />
                  <span>亿</span>
                </label>
              </div>
          </article>
          <article class="kline-filter-card" :class="{ 'is-off': !hmFilterEnabled }">
            <header class="kline-filter-card__head">
              <span class="kline-filter-card__name">有游资操作记录的</span>
              <el-switch v-model="hmFilterEnabled" size="small" @change="onHmFilterChange" />
            </header>
            <div class="kline-filter-card__body">
              <el-select
                v-model="hmName"
                class="kline-hm-select"
                size="small"
                filterable
                :disabled="!hmFilterEnabled"
                :teleported="true"
                placeholder="全部游资"
                @change="onHmNameChange"
              >
                <el-option label="全部游资" value="" />
                <el-option
                  v-for="item in hmNames"
                  :key="item.name"
                  :label="hmOptionLabel(item)"
                  :value="item.name"
                />
              </el-select>
            </div>
          </article>
          <article class="kline-filter-card">
            <header class="kline-filter-card__head">
              <span class="kline-filter-card__name">在K线上标记游资</span>
              <el-switch v-model="showHmMarks" size="small" @change="onShowHmMarksChange" />
            </header>
            <p class="kline-filter-note">开启后，有游资操作的K线上显示蓝色「游」。选中具体游资时，该游资当天改为橙色名称。此开关不筛选股票。</p>
          </article>
          <article class="kline-filter-card">
            <header class="kline-filter-card__head">
              <span class="kline-filter-card__name">在K线上标记大宗交易</span>
              <el-switch v-model="showBlockMarks" size="small" @change="onShowBlockMarksChange" />
            </header>
            <p class="kline-filter-note">开启后，有大宗交易的K线上显示紫色「宗」。同一天还有「游」时，「宗」叠在「游」上方。此开关不筛选股票。</p>
          </article>
        </div>
      </div>
    </div>
    <el-dialog
      v-model="dayDialog.visible"
      :title="dayDialogTitle"
      width="880px"
      append-to-body
      align-center
      class="kline-day-dialog"
    >
      <div class="kline-day">
        <nav class="kline-day__nav" aria-label="当天详情">
          <button
            type="button"
            :class="{ 'is-on': dayDialog.panel === 'mark' }"
            @click="dayDialog.panel = 'mark'"
          >
            原因标记
          </button>
          <button
            type="button"
            :class="{ 'is-on': dayDialog.panel === 'hm' }"
            @click="dayDialog.panel = 'hm'"
          >
            游资详情
          </button>
          <button
            type="button"
            :class="{ 'is-on': dayDialog.panel === 'block' }"
            @click="dayDialog.panel = 'block'"
          >
            大宗交易
          </button>
        </nav>
        <section v-if="dayDialog.panel === 'mark'" class="kline-day__main">
          <h3>原因标记</h3>
          <el-radio-group v-model="dayDialog.markType" class="mark-type-group">
            <el-radio value="correct" class="mark-type-correct">正确点</el-radio>
            <el-radio value="fail" class="mark-type-fail">失败点</el-radio>
          </el-radio-group>
          <el-input
            v-model="dayDialog.reason"
            class="mark-reason"
            type="textarea"
            :rows="4"
            :placeholder="markReasonPlaceholder"
            maxlength="500"
            show-word-limit
          />
          <p v-if="dayDialog.existing" class="hint mark-hint">
            当前已标记为「{{ markTypeLabel(dayDialog.existing.mark_type) }}」
            <template v-if="dayDialog.existing.reason">：{{ dayDialog.existing.reason }}</template>
          </p>
          <p v-else class="hint mark-hint">当日还没有原因标记。</p>
          <div class="kline-day-actions">
            <el-button
              v-if="dayDialog.existing"
              type="danger"
              plain
              :loading="dayDialog.saving"
              @click="removeMark"
            >
              删除
            </el-button>
            <el-button type="primary" :loading="dayDialog.saving" @click="saveMark">
              确定
            </el-button>
          </div>
        </section>
        <section v-else-if="dayDialog.panel === 'hm'" class="kline-day__main">
          <h3>游资详情</h3>
          <p v-if="!dayHmGroups.length" class="hint">当日没有游资操作。</p>
          <div v-else class="kline-hm-body">
            <ul class="kline-hm-list">
              <li v-for="group in dayHmGroups" :key="group.name">
                <button
                  type="button"
                  class="kline-hm-item"
                  :class="{ 'is-on': group.name === activeHmName }"
                  @click="dayDialog.focusName = group.name"
                >
                  <span class="kline-hm-item__name">{{ group.name }}</span>
                  <span class="kline-hm-item__meta">
                    <b :class="pctClass(group.net)">{{ formatSignedAmount(group.net) }}</b>
                    <span>{{ group.rows.length }} 笔</span>
                  </span>
                </button>
              </li>
            </ul>
            <div v-if="activeHmGroup" class="kline-hm-detail">
              <header class="kline-op-head">
                <span>{{ activeHmGroup.name }}</span>
                <b :class="pctClass(activeHmGroup.net)">{{ formatSignedAmount(activeHmGroup.net) }}</b>
              </header>
              <article
                v-for="row in activeHmGroup.rows"
                :key="row.record_no"
                class="kline-op"
              >
                <div class="kline-op__amounts">
                  <span>买入 <b>{{ formatAmount(row.buy_amount, '元') }}</b></span>
                  <span>卖出 <b>{{ formatAmount(row.sell_amount, '元') }}</b></span>
                  <span>
                    净买卖
                    <b :class="pctClass(row.net_amount)">{{ formatSignedAmount(row.net_amount) }}</b>
                  </span>
                </div>
                <p v-if="row.tag" class="kline-op__tag">{{ row.tag }}</p>
                <p class="kline-op__orgs">{{ row.hm_orgs || '没有关联机构' }}</p>
              </article>
            </div>
          </div>
        </section>
        <section v-else class="kline-day__main">
          <h3>
            大宗交易
            <span v-if="dayBlockTrades.length" class="hint">
              {{ dayBlockTrades.length }} 笔 · 合计 {{ formatAmount(dayBlockAmount, '万元') }}
            </span>
          </h3>
          <p v-if="!dayBlockTrades.length" class="hint">当日没有大宗交易。</p>
          <div v-else class="kline-hm-body">
            <ul class="kline-hm-list">
              <li v-for="(row, index) in dayBlockTrades" :key="row.record_no">
                <button
                  type="button"
                  class="kline-hm-item"
                  :class="{ 'is-on': row.record_no === activeBlockRecord }"
                  @click="dayDialog.focusRecord = row.record_no"
                >
                  <span class="kline-hm-item__name">{{ index + 1 }}. {{ formatBlockPrice(row.price) }}</span>
                  <span class="kline-hm-item__meta">
                    <b>{{ formatAmount(row.amount, '万元') }}</b>
                    <span :class="premiumClass(row.premium_rate)">{{ premiumLabel(row.premium_rate) }}</span>
                  </span>
                </button>
              </li>
            </ul>
            <div v-if="activeBlockTrade" class="kline-hm-detail">
              <header class="kline-op-head">
                <span>第 {{ activeBlockIndex + 1 }} 笔</span>
                <b>{{ formatAmount(activeBlockTrade.amount, '万元') }}</b>
              </header>
              <article class="kline-op">
                <div class="kline-op__amounts">
                  <span>成交价 <b>{{ formatBlockPrice(activeBlockTrade.price) }}</b></span>
                  <span>收盘价 <b>{{ formatPrice(activeBlockTrade.close) }}</b></span>
                  <span>
                    折溢价
                    <b :class="premiumClass(activeBlockTrade.premium_rate)">{{ premiumLabel(activeBlockTrade.premium_rate) }}</b>
                  </span>
                  <span>成交量 <b>{{ formatBlockVol(activeBlockTrade.vol) }}</b></span>
                  <span>成交金额 <b>{{ formatAmount(activeBlockTrade.amount, '万元') }}</b></span>
                </div>
                <p class="kline-op__orgs">买方 {{ activeBlockTrade.buyer || '—' }}</p>
                <p class="kline-op__orgs">卖方 {{ activeBlockTrade.seller || '—' }}</p>
              </article>
            </div>
          </div>
        </section>
      </div>
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
  formatNumber,
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
import { premiumKind, premiumLabel } from '../utils/block-trade-chart.js'
import { orderCandleMarkers } from '../utils/kline-markers.js'

const DEFAULT_MIN_MV_YI = 1
const DEFAULT_MAX_MV_YI = 10000
const MARK_COLOR_CORRECT = '#ffd54f'
const MARK_COLOR_FAIL = '#ff3dce'
const METRICS_STORAGE_KEY = 'qlab.kline.metrics'
const SETTINGS_OPEN_KEY = 'qlab.kline.settingsOpen'
const MV_FILTER_KEY = 'qlab.kline.mvFilter'
const HM_FILTER_KEY = 'qlab.kline.hmFilter'
const HM_NAME_KEY = 'qlab.kline.hmName'
const HM_MARK_KEY = 'qlab.kline.hmMarks'
const BLOCK_MARK_KEY = 'qlab.kline.blockMarks'
const DAY_PANEL_KEY = 'qlab.kline.dayPanel'
const DAY_PANELS = new Set(['mark', 'hm', 'block'])
const HM_MARK_COLOR = '#7eb6ff'
const HM_MARK_COLOR_NAMED = '#ff9f1a'
const BLOCK_MARK_COLOR = '#d7b3ff'
const MARK_STACK_REASON = 0
const MARK_STACK_HM = 1
const MARK_STACK_BLOCK = 2
const DEFAULT_METRICS = {
  dc: 'net_amount',
  ths: 'net_amount',
  l2: 'net_amount',
}
const STOCK_SCOPES = [
  { value: 'all', label: '全部' },
  { value: 'signal', label: '有信号' },
]
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

function readStoredBool(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    if (raw === '1') return true
    if (raw === '0') return false
  } catch {
    return fallback
  }
  return fallback
}

function readStoredText(key) {
  try {
    return localStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

function readStoredPanel() {
  const raw = readStoredText(DAY_PANEL_KEY)
  return DAY_PANELS.has(raw) ? raw : 'mark'
}

const selectedCode = ref('')
const settingsOpen = ref(readStoredBool(SETTINGS_OPEN_KEY, false))
const stockScope = ref('all')
const mvFilterEnabled = ref(readStoredBool(MV_FILTER_KEY, true))
const hmFilterEnabled = ref(readStoredBool(HM_FILTER_KEY, false))
const hmName = ref(readStoredText(HM_NAME_KEY))
const showHmMarks = ref(readStoredBool(HM_MARK_KEY, true))
const showBlockMarks = ref(readStoredBool(BLOCK_MARK_KEY, true))
const hmNames = ref([])
const minMvYi = ref(DEFAULT_MIN_MV_YI)
const maxMvYi = ref(DEFAULT_MAX_MV_YI)
const stockOptions = ref([])
const stock = ref(null)
let defaultStock = null
let appliedMvEnabled = mvFilterEnabled.value
let appliedMinMvYi = DEFAULT_MIN_MV_YI
let appliedMaxMvYi = DEFAULT_MAX_MV_YI
const dailyRows = ref([])
const dcRows = ref([])
const thsRows = ref([])
const l2Rows = ref([])
const hmRows = ref([])
const blockRows = ref([])
function loadStoredMetrics() {
  const next = { ...DEFAULT_METRICS }
  try {
    const raw = localStorage.getItem(METRICS_STORAGE_KEY)
    if (!raw) return next
    const saved = JSON.parse(raw)
    if (!saved || typeof saved !== 'object') return next
    const panes = { dc: DC_FIELDS, ths: THS_FIELDS, l2: L2_FIELDS }
    for (const id of Object.keys(DEFAULT_METRICS)) {
      if (panes[id].some((field) => field.id === saved[id])) next[id] = saved[id]
    }
  } catch {
    return next
  }
  return next
}

const metrics = reactive(loadStoredMetrics())

watch(
  metrics,
  (value) => {
    localStorage.setItem(METRICS_STORAGE_KEY, JSON.stringify(value))
  },
  { deep: true },
)

const error = ref('')
const loading = ref(false)
const hoverDate = ref('')
const marks = ref([])
const dayDialog = reactive({
  visible: false,
  tradeDate: '',
  markType: 'correct',
  reason: '',
  existing: null,
  saving: false,
  focusName: '',
  focusRecord: null,
  panel: readStoredPanel(),
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
  dayDialog.markType === 'fail' ? '失败的原因（可选）' : '正确的原因（可选）',
)

const dayDialogTitle = computed(() => {
  const name = stock.value?.name || stock.value?.ts_code || ''
  return ['详情', name, dayDialog.tradeDate].filter(Boolean).join(' · ')
})

function hmOptionLabel(item) {
  const count = Number(item.ops) || 0
  return `${item.name}（${count.toLocaleString('zh-CN')}）`
}

function formatSignedAmount(value) {
  const text = formatAmount(value, '元')
  if (text === '—' || Number(value) < 0) return text
  if (Number(value) > 0) return `+${text}`
  return text
}

function textMarks(dates, idPrefix, text, color, stack) {
  return [...dates].map((time) => ({
    id: `${idPrefix}-${time}`,
    time,
    position: 'aboveBar',
    shape: 'circle',
    color,
    text,
    size: 0,
    stack,
  }))
}

function candleMarkers() {
  const reasonMarks = marks.value.map((item) => {
    const isCorrect = item.mark_type !== 'fail'
    return {
      id: String(item.id),
      time: item.trade_date,
      position: isCorrect ? 'belowBar' : 'aboveBar',
      shape: isCorrect ? 'arrowUp' : 'arrowDown',
      color: isCorrect ? MARK_COLOR_CORRECT : MARK_COLOR_FAIL,
      text: isCorrect ? '正' : '败',
      size: 1.4,
      stack: MARK_STACK_REASON,
    }
  })
  const candleDates = new Set(dailyRows.value.map((row) => row.trade_date))
  const markers = [...reasonMarks]
  if (showHmMarks.value) {
    const selectedName = hmName.value
    const namedDates = new Set()
    const dates = new Set()
    for (const row of hmRows.value) {
      if (!candleDates.has(row.trade_date)) continue
      dates.add(row.trade_date)
      if (selectedName && row.hm_name === selectedName) namedDates.add(row.trade_date)
    }
    const plainDates = [...dates].filter((time) => !namedDates.has(time))
    markers.push(
      ...textMarks(plainDates, 'hm', '游', HM_MARK_COLOR, MARK_STACK_HM),
      ...textMarks(namedDates, 'hm', selectedName, HM_MARK_COLOR_NAMED, MARK_STACK_HM),
    )
  }
  if (showBlockMarks.value) {
    const dates = new Set()
    for (const row of blockRows.value) {
      if (candleDates.has(row.trade_date)) dates.add(row.trade_date)
    }
    markers.push(...textMarks(dates, 'block', '宗', BLOCK_MARK_COLOR, MARK_STACK_BLOCK))
  }
  return orderCandleMarkers(markers)
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

const hoverStats = computed(() => quoteOf(activeDaily.value))

function quoteOf(row) {
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
}

const dayHmGroups = computed(() => {
  const date = dayDialog.tradeDate
  if (!date) return []
  const groups = new Map()
  for (const row of hmRows.value) {
    if (row.trade_date !== date || !row.hm_name) continue
    let group = groups.get(row.hm_name)
    if (!group) {
      group = { name: row.hm_name, net: 0, rows: [] }
      groups.set(row.hm_name, group)
    }
    group.net += Number(row.net_amount) || 0
    group.rows.push(row)
  }
  return [...groups.values()].sort((a, b) => Math.abs(b.net) - Math.abs(a.net))
})

const activeHmGroup = computed(
  () =>
    dayHmGroups.value.find((group) => group.name === dayDialog.focusName) ||
    dayHmGroups.value[0] ||
    null,
)

const activeHmName = computed(() => activeHmGroup.value?.name || '')

const dayBlockTrades = computed(() => {
  const date = dayDialog.tradeDate
  if (!date) return []
  return blockRows.value.filter((row) => row.trade_date === date)
})

const dayBlockAmount = computed(() =>
  dayBlockTrades.value.reduce((sum, row) => sum + (Number(row.amount) || 0), 0),
)

const activeBlockTrade = computed(
  () =>
    dayBlockTrades.value.find((row) => row.record_no === dayDialog.focusRecord) ||
    dayBlockTrades.value[0] ||
    null,
)

const activeBlockRecord = computed(() => activeBlockTrade.value?.record_no ?? null)

const activeBlockIndex = computed(() => {
  const row = activeBlockTrade.value
  if (!row) return 0
  const index = dayBlockTrades.value.findIndex((item) => item.record_no === row.record_no)
  return index < 0 ? 0 : index
})

function premiumClass(value) {
  return ['kline-premium', premiumKind(value)]
}

function formatBlockPrice(value) {
  return formatNumber(value, 4)
}

function formatBlockVol(value) {
  const text = formatNumber(value, 4)
  return text === '—' ? text : `${text} 万股`
}

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
    color: (row.close ?? 0) >= (row.open ?? 0) ? 'rgba(253, 68, 50, 0.5)' : 'rgba(47, 163, 49, 0.5)',
  }))

  return [
    {
      id: 'candle',
      type: 'candlestick',
      paneIndex: 0,
      data: candles,
      options: {
        upColor: 'rgb(253, 68, 50)',
        downColor: 'rgb(47, 163, 49)',
        borderVisible: false,
        wickUpColor: 'rgb(253, 68, 50)',
        wickDownColor: 'rgb(47, 163, 49)',
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

const priceScales = computed(() => {
  const layers = Number(showHmMarks.value) + Number(showBlockMarks.value)
  return {
    right: { scaleMargins: { top: 0.08 + layers * 0.045, bottom: 0.04 } },
  }
})

async function loadStock(item) {
  const seq = ++loadSeq
  stock.value = item
  hoverDate.value = ''
  dayDialog.visible = false
  loading.value = true
  error.value = ''
  const code = encodeURIComponent(item.ts_code)
  try {
    const [daily, dc, ths, l2, markData, basic, hm, block] = await Promise.all([
      getJson(`/api/daily/${code}`),
      getJson(`/api/moneyflow/${code}?source=dc`),
      getJson(`/api/moneyflow/${code}?source=ths`),
      getJson(`/api/moneyflow/${code}?source=l2`),
      getJson(`/api/marks/${code}`),
      getJson(`/api/daily-basic/${code}`).catch(() => ({ item: null })),
      getJson(`/api/hm/detail/${code}`).catch(() => ({ rows: [] })),
      getJson(`/api/block-trades/${code}`).catch(() => ({ rows: [] })),
    ])
    if (seq !== loadSeq) return
    stock.value = { ...item, total_mv: basic.item?.total_mv ?? null }
    dailyRows.value = daily.rows || []
    dcRows.value = dc.rows || []
    thsRows.value = ths.rows || []
    l2Rows.value = l2.rows || []
    marks.value = markData.items || []
    hmRows.value = hm.rows || []
    blockRows.value = block.rows || []
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
    hmRows.value = []
    blockRows.value = []
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

function normalizeMaxMvYi(value) {
  if (value === '' || value == null) return DEFAULT_MAX_MV_YI
  const n = Number(value)
  if (!Number.isFinite(n) || n < 0) return DEFAULT_MAX_MV_YI
  return n
}

function emptyStockMessage() {
  const bits = []
  if (mvFilterEnabled.value) {
    const max = maxMvYi.value
    bits.push(
      max == null
        ? `市值大于等于 ${minMvYi.value} 亿`
        : `市值 ${minMvYi.value}～${max} 亿`,
    )
  }
  if (stockScope.value === 'signal') bits.push('有信号')
  if (hmFilterEnabled.value) {
    bits.push(hmName.value ? `游资「${hmName.value}」有操作` : '有游资操作记录')
  }
  if (!bits.length) return '没有股票'
  return `没有${bits.join('、')}的股票`
}

async function loadStockList(preferredCode) {
  const enabled = mvFilterEnabled.value
  const min = normalizeMinMvYi(minMvYi.value)
  const max = normalizeMaxMvYi(maxMvYi.value)
  minMvYi.value = min
  maxMvYi.value = max
  appliedMvEnabled = enabled
  appliedMinMvYi = min
  appliedMaxMvYi = max
  const scope = stockScope.value
  const params = new URLSearchParams()
  if (enabled) {
    params.set('minMvYi', String(min))
    params.set('maxMvYi', String(max))
  }
  if (scope === 'signal') params.set('scope', 'signal')
  if (hmFilterEnabled.value) {
    params.set('hm', '1')
    if (hmName.value) params.set('hmName', hmName.value)
  }
  const list = await getJson(`/api/stocks?${params}`)
  stockOptions.value = (list.items || []).map(toStockOption)
  if (!stockOptions.value.length) {
    selectedCode.value = ''
    stock.value = null
    dailyRows.value = []
    dcRows.value = []
    thsRows.value = []
    l2Rows.value = []
    marks.value = []
    hmRows.value = []
    blockRows.value = []
    error.value = emptyStockMessage()
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

const onMvRangeChange = debounce(() => {
  const enabled = mvFilterEnabled.value
  const min = normalizeMinMvYi(minMvYi.value)
  const max = normalizeMaxMvYi(maxMvYi.value)
  minMvYi.value = min
  maxMvYi.value = max
  if (
    enabled === appliedMvEnabled &&
    min === appliedMinMvYi &&
    max === appliedMaxMvYi
  ) {
    return
  }
  loadStockList().catch((err) => {
    error.value = err.message
  })
}, 400)

watch(settingsOpen, (value) => {
  localStorage.setItem(SETTINGS_OPEN_KEY, value ? '1' : '0')
})

watch(
  () => dayDialog.panel,
  (value) => {
    localStorage.setItem(DAY_PANEL_KEY, DAY_PANELS.has(value) ? value : 'mark')
  },
)

watch(mvFilterEnabled, (value) => {
  localStorage.setItem(MV_FILTER_KEY, value ? '1' : '0')
})

watch([minMvYi, maxMvYi, mvFilterEnabled], () => {
  onMvRangeChange()
})

function onStockScopeChange() {
  loadStockList().catch((err) => {
    error.value = err.message
  })
}

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

function onHmFilterChange(value) {
  localStorage.setItem(HM_FILTER_KEY, value ? '1' : '0')
  loadStockList().catch((err) => {
    error.value = err.message
  })
}

function onHmNameChange(value) {
  localStorage.setItem(HM_NAME_KEY, value || '')
  if (!hmFilterEnabled.value) return
  loadStockList().catch((err) => {
    error.value = err.message
  })
}

function onShowHmMarksChange(value) {
  localStorage.setItem(HM_MARK_KEY, value ? '1' : '0')
}

function onShowBlockMarksChange(value) {
  localStorage.setItem(BLOCK_MARK_KEY, value ? '1' : '0')
}

function onChartClick(payload) {
  if (payload.paneIndex !== 0 || loading.value || !stock.value) return
  const tradeDate = toTradeDate(payload.time)
  if (!tradeDate) return
  if (!dailyRows.value.some((row) => row.trade_date === tradeDate)) return

  const existing =
    marks.value.find((item) => item.trade_date === tradeDate) || null
  const preferred = hmFilterEnabled.value ? hmName.value : ''
  const dayNames = hmRows.value
    .filter((row) => row.trade_date === tradeDate)
    .map((row) => row.hm_name)
  dayDialog.tradeDate = tradeDate
  dayDialog.existing = existing
  dayDialog.markType = existing ? existing.mark_type : 'correct'
  dayDialog.reason = existing?.reason || ''
  const dayBlocks = blockRows.value.filter((row) => row.trade_date === tradeDate)
  dayDialog.focusName =
    preferred && dayNames.includes(preferred) ? preferred : dayNames[0] || ''
  dayDialog.focusRecord = dayBlocks[0]?.record_no ?? null
  dayDialog.visible = true
}

async function saveMark() {
  if (!stock.value || dayDialog.saving) return
  dayDialog.saving = true
  try {
    const data = await sendJson('/api/marks', 'POST', {
      ts_code: stock.value.ts_code,
      trade_date: dayDialog.tradeDate,
      mark_type: dayDialog.markType,
      reason: dayDialog.reason.trim(),
    })
    const item = data.item
    const index = marks.value.findIndex(
      (row) => row.trade_date === item.trade_date,
    )
    if (index >= 0) marks.value.splice(index, 1, item)
    else marks.value.push(item)
    dayDialog.existing = item
    dayDialog.reason = item.reason || ''
    ElMessage.success(`已标记${markTypeLabel(item.mark_type)} ${item.trade_date}`)
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    dayDialog.saving = false
  }
}

async function removeMark() {
  const existing = dayDialog.existing
  if (!existing || dayDialog.saving) return
  dayDialog.saving = true
  try {
    await sendJson(`/api/marks/${existing.id}`, 'DELETE')
    marks.value = marks.value.filter((item) => item.id !== existing.id)
    dayDialog.existing = null
    dayDialog.markType = 'correct'
    dayDialog.reason = ''
    ElMessage.success(`已删除 ${existing.trade_date} 的标记`)
    if (stockScope.value === 'signal' && marks.value.length === 0) {
      await loadStockList()
    }
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    dayDialog.saving = false
  }
}

onMounted(async () => {
  try {
    const [meta, names] = await Promise.all([
      getJson('/api/meta'),
      getJson('/api/hm/names').catch(() => ({ items: [] })),
    ])
    hmNames.value = names.items || []
    if (hmName.value && !hmNames.value.some((item) => item.name === hmName.value)) {
      hmName.value = ''
      localStorage.setItem(HM_NAME_KEY, '')
    }
    defaultStock = meta.defaultStock || null
    await loadStockList(defaultStock?.ts_code)
  } catch (err) {
    error.value = err.message
  }
})
</script>
