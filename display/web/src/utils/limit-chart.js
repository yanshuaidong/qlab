export function createLimitChartOption(rows) {
  const peak = Math.max(1, ...rows.flatMap(row => [row.up, row.down]))
  const bound = Math.ceil(peak / 10) * 10
  return {
    backgroundColor: 'transparent',
    animationDuration: 250,
    grid: { left: 68, right: 32, top: 65, bottom: 94 },
    legend: { top: 12, data: ['涨停', '跌停'], selectedMode: false },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: value => value == null ? '—' : `${Math.abs(value)} 只`,
    },
    xAxis: {
      type: 'category',
      name: '交易日期',
      nameLocation: 'middle',
      nameGap: 34,
      data: rows.map(row => row.date),
      axisLabel: { formatter: value => value.slice(5), hideOverlap: true },
      axisLine: { onZero: false, lineStyle: { color: '#8b95a8' } },
      axisTick: { alignWithLabel: true },
    },
    yAxis: {
      type: 'value',
      name: '股票数量（只）',
      min: -bound,
      max: bound,
      minInterval: 1,
      axisLabel: { formatter: value => Math.abs(value) },
      splitLine: { lineStyle: { color: '#243044' } },
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', bottom: 12, height: 24, start: 0, end: 100, borderColor: '#243044' },
    ],
    // 同一 stack 的正负值分别从零轴出发，保证同一天的上下柱水平对齐。
    series: [
      { name: '涨停', color: '#fd4432', values: rows.map(row => row.eligibleStocks ? row.up : null) },
      { name: '跌停', color: '#2fa331', values: rows.map(row => row.eligibleStocks ? -row.down : null) },
    ].map(series => ({
      name: series.name,
      type: 'bar',
      stack: 'limits',
      data: series.values,
      itemStyle: { color: series.color },
      barMaxWidth: 18,
      emphasis: { focus: 'series' },
    })),
  }
}

export function createMainForceChartOption(rows) {
  const peak = Math.max(1, ...rows.map(row => row.count))
  const bound = Math.ceil(peak / 10) * 10
  return {
    backgroundColor: 'transparent',
    animationDuration: 250,
    grid: { left: 68, right: 32, top: 65, bottom: 94 },
    legend: { top: 12, data: ['主力风向'], selectedMode: false },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: value => value == null ? '—' : `${value} 只`,
    },
    xAxis: {
      type: 'category',
      name: '交易日期',
      nameLocation: 'middle',
      nameGap: 34,
      data: rows.map(row => row.date),
      axisLabel: { formatter: value => value.slice(5), hideOverlap: true },
      axisLine: { onZero: false, lineStyle: { color: '#8b95a8' } },
      axisTick: { alignWithLabel: true },
    },
    yAxis: {
      type: 'value',
      name: '股票数量（只）',
      min: 0,
      max: bound,
      minInterval: 1,
      splitLine: { lineStyle: { color: '#243044' } },
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', bottom: 12, height: 24, start: 0, end: 100, borderColor: '#243044' },
    ],
    series: [{
      name: '主力风向',
      type: 'bar',
      data: rows.map(row => row.count),
      itemStyle: { color: '#3d8bfd' },
      barMaxWidth: 18,
    }],
  }
}
