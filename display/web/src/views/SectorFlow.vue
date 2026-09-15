<template>
  <section class="page">
    <div class="toolbar">
      <span class="toolbar-label">数据源</span>
      <el-select v-model="source" style="width: 140px">
        <el-option label="东财板块" value="dc" />
        <el-option label="同花顺行业" value="ths_ind" />
        <el-option label="同花顺概念" value="ths_cnt" />
      </el-select>
      <template v-if="source === 'dc'">
        <span class="toolbar-label">类型</span>
        <el-select v-model="contentType" style="width: 110px">
          <el-option label="行业" value="行业" />
          <el-option label="概念" value="概念" />
          <el-option label="地域" value="地域" />
        </el-select>
      </template>
      <span class="toolbar-label">交易日</span>
      <el-date-picker
        v-model="date"
        type="date"
        value-format="YYYY-MM-DD"
        placeholder="交易日"
        style="width: 160px"
      />
      <el-text class="status" :type="error ? 'danger' : 'info'">
        {{ error || status }}
      </el-text>
    </div>
    <div class="sector-body">
      <div class="table-wrap">
        <el-table
          ref="tableRef"
          v-loading="loading"
          :data="rows"
          row-key="ts_code"
          height="100%"
          size="small"
          highlight-current-row
          @row-click="selectSector"
        >
          <el-table-column prop="ts_code" label="代码" min-width="110" />
          <el-table-column
            prop="name"
            label="名称"
            min-width="120"
            show-overflow-tooltip
          />
          <el-table-column label="涨跌幅%" min-width="90" align="right">
            <template #default="{ row }">
              <span :class="pctClass(row.pct_change)">
                {{ formatNumber(row.pct_change) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="净流入" min-width="110" align="right">
            <template #default="{ row }">
              <span :class="pctClass(row.net_amount)">
                {{ formatAmount(row.net_amount, unit) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column
            prop="lead_stock"
            label="领涨股"
            min-width="110"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              {{ row.lead_stock || '—' }}
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="chart-wrap">
        <ChartPane :series="chartSeries" :price-scales="priceScales" />
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import ChartPane from '../components/ChartPane.vue'
import {
  flowColor,
  formatAmount,
  formatNumber,
  getJson,
  pctClass,
} from '../api.js'

const source = ref('dc')
const contentType = ref('行业')
const date = ref('')
const rows = ref([])
const unit = ref('元')
const selected = ref(null)
const seriesRows = ref([])
const error = ref('')
const loading = ref(false)
const tableRef = ref(null)
let syncingDate = false

const status = computed(() => {
  if (loading.value) return '加载中…'
  const name = selected.value ? ` · ${selected.value.name}` : ''
  return `${date.value || '—'} · ${rows.value.length} 条${name} · 单位 ${unit.value}`
})

const priceScales = {
  index: {
    position: 'left',
    borderColor: '#2a3344',
  },
}

const chartSeries = computed(() => [
  {
    id: 'sector-net',
    type: 'histogram',
    data: seriesRows.value.map((row) => ({
      time: row.trade_date,
      value: row.net_amount ?? 0,
      color: flowColor(row.net_amount),
    })),
    options: {
      lastValueVisible: false,
      priceLineVisible: false,
      priceFormat: {
        type: 'custom',
        formatter: (value) => formatAmount(value, unit.value),
      },
    },
  },
  {
    id: 'sector-close',
    type: 'line',
    data: seriesRows.value
      .filter((row) => row.close != null)
      .map((row) => ({ time: row.trade_date, value: row.close })),
    options: {
      color: '#61afef',
      lineWidth: 2,
      priceScaleId: 'index',
      lastValueVisible: true,
      priceLineVisible: false,
    },
  },
])

async function syncCurrentRow() {
  await nextTick()
  tableRef.value?.setCurrentRow(selected.value)
}

async function loadList() {
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({ source: source.value })
    if (date.value) params.set('date', date.value)
    if (source.value === 'dc') params.set('type', contentType.value)
    const data = await getJson(`/api/sectors?${params.toString()}`)
    rows.value = data.rows || []
    unit.value = data.unit || '元'
    if (data.date && data.date !== date.value) {
      syncingDate = true
      date.value = data.date
      await nextTick()
      syncingDate = false
    }
    if (rows.value.length) {
      const keep = rows.value.find((row) => row.ts_code === selected.value?.ts_code)
      await selectSector(keep || rows.value[0])
    } else {
      selected.value = null
      seriesRows.value = []
      await syncCurrentRow()
    }
  } catch (err) {
    error.value = err.message
    rows.value = []
    seriesRows.value = []
  } finally {
    loading.value = false
  }
}

async function selectSector(row) {
  selected.value = row
  await syncCurrentRow()
  try {
    const data = await getJson(
      `/api/sector/${encodeURIComponent(row.ts_code)}?source=${source.value}`,
    )
    seriesRows.value = data.rows || []
    unit.value = data.unit || unit.value
  } catch (err) {
    error.value = err.message
    seriesRows.value = []
  }
}

watch([source, contentType], () => {
  selected.value = null
  loadList()
})

watch(date, () => {
  if (syncingDate) return
  loadList()
})

onMounted(loadList)
</script>
