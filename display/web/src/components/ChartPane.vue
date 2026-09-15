<template>
  <div ref="el" class="chart-pane"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts'

const TYPE_MAP = {
  candlestick: CandlestickSeries,
  histogram: HistogramSeries,
  line: LineSeries,
}

const props = defineProps({
  series: { type: Array, default: () => [] },
  priceScales: { type: Object, default: () => ({}) },
  paneStretch: { type: Array, default: () => [] },
  fitToken: { default: null },
})

const emit = defineEmits(['click'])

const el = ref(null)
let chart = null
const seriesMap = new Map()
const markersMap = new Map()
let lastFitToken = Symbol('unfitted')

const chartOptions = {
  autoSize: true,
  layout: {
    background: { type: ColorType.Solid, color: '#161b26' },
    textColor: '#9aa4b2',
    fontFamily: 'Segoe UI, PingFang SC, Microsoft YaHei, sans-serif',
  },
  grid: {
    vertLines: { color: '#1a2230' },
    horzLines: { color: '#1a2230' },
  },
  rightPriceScale: {
    borderColor: '#2a3344',
  },
  timeScale: {
    borderColor: '#2a3344',
    timeVisible: false,
  },
  crosshair: {
    mode: CrosshairMode.Normal,
  },
}

function applySeries() {
  if (!chart) return

  const ids = new Set(props.series.map((spec) => spec.id))
  for (const [id, series] of seriesMap) {
    if (!ids.has(id)) {
      markersMap.get(id)?.detach()
      markersMap.delete(id)
      chart.removeSeries(series)
      seriesMap.delete(id)
    }
  }

  for (const spec of props.series) {
    let series = seriesMap.get(spec.id)
    if (!series) {
      series = chart.addSeries(
        TYPE_MAP[spec.type],
        spec.options || {},
        spec.paneIndex ?? 0,
      )
      seriesMap.set(spec.id, series)
    } else if (spec.options) {
      series.applyOptions(spec.options)
    }
    series.setData(spec.data || [])
    if (spec.priceScale) {
      series.priceScale().applyOptions(spec.priceScale)
    }
    if (Array.isArray(spec.markers) || markersMap.has(spec.id)) {
      const next = Array.isArray(spec.markers) ? spec.markers : []
      let markers = markersMap.get(spec.id)
      if (!markers) {
        markers = createSeriesMarkers(series, next)
        markersMap.set(spec.id, markers)
      } else {
        markers.setMarkers(next)
      }
    }
  }

  for (const [id, opts] of Object.entries(props.priceScales)) {
    chart.priceScale(id).applyOptions(opts)
  }

  if (props.paneStretch.length && typeof chart.panes === 'function') {
    const panes = chart.panes()
    props.paneStretch.forEach((factor, index) => {
      if (panes[index] && typeof panes[index].setStretchFactor === 'function') {
        panes[index].setStretchFactor(factor)
      }
    })
  }

  const shouldFit =
    props.fitToken == null || props.fitToken !== lastFitToken
  lastFitToken = props.fitToken
  if (shouldFit) {
    chart.timeScale().fitContent()
  }
}

function resolvePaneIndex(param) {
  if (typeof param.paneIndex === 'number') return param.paneIndex
  if (!chart || !param.point || typeof chart.panes !== 'function') return -1
  const panes = chart.panes()
  let y = param.point.y
  for (let i = 0; i < panes.length; i += 1) {
    const height = panes[i].getHeight()
    if (y <= height) return i
    y -= height
  }
  return -1
}

function handleClick(param) {
  if (param.time == null || !param.point) return
  emit('click', {
    time: param.time,
    paneIndex: resolvePaneIndex(param),
    hoveredObjectId: param.hoveredInfo?.objectId ?? param.hoveredObjectId,
  })
}

onMounted(() => {
  chart = createChart(el.value, chartOptions)
  chart.subscribeClick(handleClick)
  applySeries()
})

watch(
  () => [props.series, props.priceScales, props.paneStretch, props.fitToken],
  applySeries,
  { deep: true },
)

onBeforeUnmount(() => {
  chart?.unsubscribeClick(handleClick)
  chart?.remove()
  chart = null
  seriesMap.clear()
  markersMap.clear()
})

defineExpose({
  getChart: () => chart,
})
</script>
