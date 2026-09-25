<template>
  <section class="day-stocks" aria-label="当日信号股票">
    <div class="day-heading">
      <h2>{{ date }} · {{ groupLabel }}</h2>
      <span v-if="!loading && !error" class="hint">共 {{ total }} 只股票 · 每页 {{ pageSize }} 只，默认展开 K 线</span>
      <el-button size="small" :disabled="!items.length" @click="expanded = items.map(item => item.id)">展开本页</el-button>
      <el-button size="small" :disabled="!items.length" @click="expanded = []">收起本页</el-button>
    </div>
    <div class="day-body" v-loading="loading">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon>
        <el-button size="small" @click="load">重试股票列表</el-button>
      </el-alert>
      <el-empty v-if="!loading && !error && !items.length" description="当天没有符合筛选条件的股票" :image-size="60" />
      <article v-for="(stock, index) in items" :key="stock.id" class="stock-row">
        <button type="button" class="stock-heading" :aria-expanded="expanded.includes(stock.id)"
          :aria-controls="`signal-kline-${stock.id}`" @click="toggle(stock.id)">
          <span class="toggle-icon" aria-hidden="true">{{ expanded.includes(stock.id) ? '▾' : '▸' }}</span>
          <span class="stock-index">{{ (page - 1) * pageSize + index + 1 }}</span>
          <strong>{{ stock.name || stock.ts_code }}</strong>
          <span v-if="stock.name" class="stock-code">{{ stock.ts_code }}</span>
          <span class="signal-badge" :class="stock.mark_type">{{ stock.mark_type === 'correct' ? '好信号' : '差信号' }}</span>
          <span class="stock-code">信号日期：{{ stock.trade_date }}</span>
          <span class="toggle-label">{{ expanded.includes(stock.id) ? '收起 K 线' : '展开 K 线' }}</span>
        </button>
        <div v-if="expanded.includes(stock.id)" :id="`signal-kline-${stock.id}`">
          <SignalStockKline :signal="stock" />
          <details v-if="stock.reason" class="signal-reason">
            <summary>查看信号原因</summary>
            <p>{{ stock.reason }}</p>
          </details>
        </div>
      </article>
    </div>
    <el-pagination v-if="total > pageSize && !error" v-model:current-page="page"
      :page-size="pageSize" :total="total" :disabled="loading" layout="total, prev, pager, next"
      @current-change="load" />
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getJson } from '../api.js'
import SignalStockKline from './SignalStockKline.vue'

const props = defineProps({ date: { type: String, required: true }, group: { type: String, required: true } })
const pageSize = 10
const page = ref(1)
const items = ref([])
const total = ref(0)
const expanded = ref([])
const loading = ref(false)
const error = ref('')
const groupLabel = computed(() => ({ total: '全部信号', correct: '仅好信号', fail: '仅差信号' })[props.group])
let controller
function toggle(id) {
  expanded.value = expanded.value.includes(id) ? expanded.value.filter(value => value !== id) : [...expanded.value, id]
}
async function load() {
  controller?.abort()
  const request = new AbortController()
  controller = request
  loading.value = true
  error.value = ''
  items.value = []
  expanded.value = []
  try {
    const query = new URLSearchParams({ date: props.date, group: props.group, page: page.value, pageSize })
    const result = await getJson(`/api/signal-analysis/signals?${query}`, { signal: request.signal })
    if (request.signal.aborted) return
    items.value = result.items
    total.value = result.total
    expanded.value = result.items.map(item => item.id)
  } catch (err) {
    if (!request.signal.aborted) error.value = err.message
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}
watch(() => [props.date, props.group], () => {
  page.value = 1
  total.value = 0
  load()
}, { immediate: true })
onBeforeUnmount(() => controller?.abort())
</script>

<style scoped>
.day-stocks { flex: 0 0 auto; scroll-margin-top: 12px; }
.day-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
h2 { font-size: 16px; margin: 0; }
.day-heading .hint { margin-right: auto; }
.day-body { min-height: 100px; }
.stock-row { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin-bottom: 14px; }
.stock-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding: 14px; width: 100%; border: 0; text-align: left; background: var(--bg-panel); color: var(--text); cursor: pointer; font: inherit; font-size: 14px; }
.stock-heading:hover { background: var(--bg-hover); }
.stock-heading:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.stock-index, .stock-code, .toggle-label { color: var(--text-dim); font-size: 12px; }
.toggle-label { margin-left: auto; }
.signal-badge { padding: 3px 8px; border: 1px solid currentColor; border-radius: 4px; font-size: 12px; }
.signal-badge.correct { color: var(--mark-correct); }
.signal-badge.fail { color: var(--mark-fail); }
.signal-reason { padding: 0 14px 14px; font-size: 13px; }
.signal-reason summary { cursor: pointer; color: var(--accent); }
.signal-reason p { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; max-height: 240px; overflow: auto; }
.el-pagination { margin: 12px 0; }
</style>
