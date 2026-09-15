<template>
  <section class="page">
    <div class="toolbar">
      <el-checkbox v-model="showElg">超大单</el-checkbox>
      <el-checkbox v-model="showLg">大单</el-checkbox>
      <el-checkbox v-model="showMd">中单</el-checkbox>
      <el-checkbox v-model="showSm">小单</el-checkbox>
      <el-checkbox v-model="showIndex">上证/深证收盘</el-checkbox>
      <el-text class="status" :type="error ? 'danger' : 'info'">
        {{ error || status }}
      </el-text>
    </div>
    <el-text class="hint" type="info">
      东财大盘资金流向，金额单位为元（图轴按亿/万缩写）。
    </el-text>
    <div class="chart-wrap">
      <ChartPane :series="chartSeries" :price-scales="priceScales" />
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import ChartPane from '../components/ChartPane.vue'
import { flowColor, formatAmount, getJson } from '../api.js'

const rows = ref([])
const unit = ref('元')
const error = ref('')
const showElg = ref(true)
const showLg = ref(true)
const showMd = ref(false)
const showSm = ref(false)
const showIndex = ref(true)

const status = computed(() => {
  if (!rows.value.length) return '暂无数据'
  return `东财大盘 · ${rows.value.length} 个交易日 · 单位 ${unit.value}`
})

const priceScales = computed(() => ({
  right: { scaleMargins: { top: 0.12, bottom: 0.08 } },
  index: {
    position: 'left',
    borderColor: '#2a3344',
    scaleMargins: { top: 0.08, bottom: 0.08 },
  },
}))

function lineSeries(id, color, data, priceScaleId) {
  return {
    id,
    type: 'line',
    data,
    options: {
      color,
      lineWidth: 2,
      priceScaleId: priceScaleId || 'right',
      lastValueVisible: true,
      priceLineVisible: false,
      priceFormat: priceScaleId
        ? { type: 'price', precision: 2, minMove: 0.01 }
        : {
            type: 'custom',
            formatter: (value) => formatAmount(value, unit.value),
          },
    },
  }
}

const chartSeries = computed(() => {
  const series = [
    {
      id: 'net',
      type: 'histogram',
      data: rows.value.map((row) => ({
        time: row.trade_date,
        value: row.net_amount ?? 0,
        color: flowColor(row.net_amount),
      })),
      options: {
        priceScaleId: 'right',
        lastValueVisible: false,
        priceLineVisible: false,
        priceFormat: {
          type: 'custom',
          formatter: (value) => formatAmount(value, unit.value),
        },
      },
    },
  ]

  if (showElg.value) {
    series.push(
      lineSeries(
        'elg',
        '#e5c07b',
        rows.value.map((row) => ({
          time: row.trade_date,
          value: row.buy_elg_amount ?? 0,
        })),
      ),
    )
  }
  if (showLg.value) {
    series.push(
      lineSeries(
        'lg',
        '#61afef',
        rows.value.map((row) => ({
          time: row.trade_date,
          value: row.buy_lg_amount ?? 0,
        })),
      ),
    )
  }
  if (showMd.value) {
    series.push(
      lineSeries(
        'md',
        '#c678dd',
        rows.value.map((row) => ({
          time: row.trade_date,
          value: row.buy_md_amount ?? 0,
        })),
      ),
    )
  }
  if (showSm.value) {
    series.push(
      lineSeries(
        'sm',
        '#98c379',
        rows.value.map((row) => ({
          time: row.trade_date,
          value: row.buy_sm_amount ?? 0,
        })),
      ),
    )
  }
  if (showIndex.value) {
    series.push(
      lineSeries(
        'sh',
        '#abb2bf',
        rows.value
          .filter((row) => row.close_sh != null)
          .map((row) => ({ time: row.trade_date, value: row.close_sh })),
        'index',
      ),
      lineSeries(
        'sz',
        '#56b6c2',
        rows.value
          .filter((row) => row.close_sz != null)
          .map((row) => ({ time: row.trade_date, value: row.close_sz })),
        'index',
      ),
    )
  }

  return series
})

onMounted(async () => {
  try {
    const data = await getJson('/api/market-flow')
    rows.value = data.rows || []
    unit.value = data.unit?.flow || '元'
  } catch (err) {
    error.value = err.message
  }
})
</script>
