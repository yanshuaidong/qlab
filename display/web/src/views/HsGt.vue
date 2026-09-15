<template>
  <section class="page">
    <div class="toolbar">
      <el-checkbox v-model="showNorth">北向</el-checkbox>
      <el-checkbox v-model="showSouth">南向</el-checkbox>
      <el-checkbox v-model="showHgt">沪股通</el-checkbox>
      <el-checkbox v-model="showSgt">深股通</el-checkbox>
      <el-text class="status" :type="error ? 'danger' : 'info'">
        {{ error || status }}
      </el-text>
    </div>
    <el-text class="hint" type="info">沪股通 / 深股通 / 北向 / 南向，单位为百万元。</el-text>
    <div class="chart-wrap">
      <ChartPane :series="chartSeries" />
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import ChartPane from '../components/ChartPane.vue'
import { formatAmount, getJson } from '../api.js'

const rows = ref([])
const unit = ref('百万元')
const error = ref('')
const showNorth = ref(true)
const showSouth = ref(true)
const showHgt = ref(false)
const showSgt = ref(false)

const status = computed(() => {
  if (!rows.value.length) return '暂无数据'
  return `沪深港通 · ${rows.value.length} 个交易日 · 单位 ${unit.value}`
})

function lineSeries(id, color, field, enabled) {
  if (!enabled) return null
  return {
    id,
    type: 'line',
    data: rows.value
      .filter((row) => row[field] != null)
      .map((row) => ({ time: row.trade_date, value: row[field] })),
    options: {
      color,
      lineWidth: 2,
      lastValueVisible: true,
      priceLineVisible: false,
      priceFormat: {
        type: 'custom',
        formatter: (value) => formatAmount(value, unit.value),
      },
    },
  }
}

const chartSeries = computed(() =>
  [
    lineSeries('north', '#ef5350', 'north_money', showNorth.value),
    lineSeries('south', '#61afef', 'south_money', showSouth.value),
    lineSeries('hgt', '#e5c07b', 'hgt', showHgt.value),
    lineSeries('sgt', '#98c379', 'sgt', showSgt.value),
  ].filter(Boolean),
)

onMounted(async () => {
  try {
    const data = await getJson('/api/hsgt')
    rows.value = data.rows || []
    unit.value = data.unit || '百万元'
  } catch (err) {
    error.value = err.message
  }
})
</script>
