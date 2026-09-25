<template>
  <div class="signal-kline" v-loading="loading">
    <div class="kline-actions">
      <span class="hint">日 K 线（未复权）· 默认展示信号前约 20、后最多 80 个交易日，可拖动／缩放查看完整历史。</span>
      <el-button size="small" :disabled="!model.rows.length" @click="focusSignal">定位信号</el-button>
      <el-button size="small" :disabled="!model.rows.length" @click="showAll">查看全部走势</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon>
      <el-button size="small" @click="load">重试 K 线</el-button>
    </el-alert>
    <el-alert v-else-if="!loading && model.rows.length && model.signalIndex < 0"
      title="缺少信号当天的 K 线，未将标记移到其他日期；已定位到邻近行情。" type="warning" :closable="false" show-icon />
    <p v-if="!loading && !error && model.rows.length" class="hint">
      行情截至 {{ model.rows.at(-1).trade_date }} · 信号后已有 {{ model.subsequentDays }} 个交易日
      <span v-if="model.subsequentDays === 0">（暂无后续行情）</span>
    </p>
    <div class="candle-legend" aria-live="polite">
      <template v-if="hoverRow">
        <span>{{ hoverRow.trade_date }}</span>
        <span>开 {{ formatPrice(hoverRow.open) }}</span>
        <span>高 {{ formatPrice(hoverRow.high) }}</span>
        <span>低 {{ formatPrice(hoverRow.low) }}</span>
        <span>收 {{ formatPrice(hoverRow.close) }}</span>
        <span>涨跌幅 {{ formatSignedPercent(hoverRow.pct_chg) }}</span>
      </template>
      <span v-else>鼠标移入 K 线查看当日价格</span>
    </div>
    <div class="candle-stage">
      <ChartPane v-if="model.rows.length && !loading && !error" ref="chartRef"
        :series="series" :fit-token="signal.id" @ready="focusSignal" @hover="onHover" />
      <el-empty v-else-if="!loading && !error" description="该股票暂无可用 K 线数据" :image-size="60" />
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ChartPane from './ChartPane.vue'
import { formatPrice, formatSignedPercent, getJson, toTradeDate } from '../api.js'
import { buildSignalKline } from '../utils/signal-kline.js'

const props = defineProps({ signal: { type: Object, required: true } })
const chartRef = ref(null)
const rows = ref([])
const hoverDate = ref('')
const error = ref('')
const loading = ref(false)
let controller
const model = computed(() => buildSignalKline(rows.value, props.signal))
const hoverRow = computed(() => model.value.rows.find(row => row.trade_date === hoverDate.value)
  || model.value.rows[model.value.signalIndex])
const series = computed(() => [{
  id: 'signal-candle',
  type: 'candlestick',
  data: model.value.candles,
  options: {
    upColor: 'rgb(253, 68, 50)',
    downColor: 'rgb(47, 163, 49)',
    wickUpColor: 'rgb(253, 68, 50)',
    wickDownColor: 'rgb(47, 163, 49)',
    borderVisible: false,
    priceLineVisible: false,
    priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
  },
  priceScale: { scaleMargins: { top: 0.15, bottom: 0.18 } },
  markers: model.value.markers,
}])

async function focusSignal() {
  await nextTick()
  if (model.value.range) chartRef.value?.getChart()?.timeScale().setVisibleLogicalRange(model.value.range)
}
function showAll() {
  chartRef.value?.getChart()?.timeScale().fitContent()
}
function onHover(event) {
  hoverDate.value = toTradeDate(event?.time)
}
async function load() {
  controller?.abort()
  const request = new AbortController()
  controller = request
  rows.value = []
  hoverDate.value = ''
  loading.value = true
  error.value = ''
  try {
    const result = await getJson(`/api/daily/${encodeURIComponent(props.signal.ts_code)}`, { signal: request.signal })
    if (request.signal.aborted) return
    rows.value = result.rows || []
  } catch (err) {
    if (!request.signal.aborted) error.value = err.message
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}
watch(() => [props.signal.ts_code, props.signal.trade_date], load, { immediate: true })
onBeforeUnmount(() => controller?.abort())
</script>

<style scoped>
.signal-kline { min-height: 420px; padding: 12px; border-top: 1px solid var(--border); }
.kline-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.kline-actions .hint { margin-right: auto; }
p.hint { margin: 10px 0 0; }
.candle-legend { display: flex; flex-wrap: wrap; gap: 8px 16px; min-height: 30px; padding: 8px 0; color: var(--text-dim); font-size: 12px; font-variant-numeric: tabular-nums; }
.candle-stage { height: 340px; }
</style>
