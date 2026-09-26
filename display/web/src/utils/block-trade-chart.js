const COLORS = { premium: '#fd4432', discount: '#2fa331', flat: '#e5bf65', unknown: '#8b95a8', mixed: '#be8cf0' }

export function premiumKind(value) {
  if (!Number.isFinite(value)) return 'unknown'
  if (Math.abs(value) < 1e-8) return 'flat'
  return value > 0 ? 'premium' : 'discount'
}

export function premiumLabel(value) {
  const kind = premiumKind(value)
  if (kind === 'unknown') return '无法计算'
  if (kind === 'flat') return '平价 0.00%'
  return `${kind === 'premium' ? '溢价' : '折价'} ${Math.abs(value).toFixed(2)}%`
}

function markerText(kind, trades) {
  const label = { premium: '溢', discount: '折', flat: '平价', unknown: '未知' }[kind]
  if (kind === 'unknown' || kind === 'flat') return `${label} ${trades.length}笔`
  const values = trades.map(row => Math.abs(row.premium_rate))
  const min = Math.min(...values).toFixed(2)
  const max = Math.max(...values).toFixed(2)
  return `${label} ${min === max ? min : `${min}~${max}`}% · ${trades.length}笔`
}

export function buildBlockTradeKline(daily = [], trades = [], showLabels = true) {
  const dailyByDate = new Map()
  for (const row of daily) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(row.trade_date)
      || !['open', 'high', 'low', 'close'].every(key => Number.isFinite(row[key]) && row[key] > 0)) continue
    dailyByDate.set(row.trade_date, row)
  }
  const byDate = new Map()
  for (const row of trades) {
    if (!byDate.has(row.trade_date)) byDate.set(row.trade_date, [])
    byDate.get(row.trade_date).push(row)
  }
  const dates = [...new Set([...dailyByDate.keys(), ...byDate.keys()])].sort()
  const markers = []
  const histogram = []
  for (const date of dates) {
    const dayTrades = byDate.get(date) || []
    const groups = new Map()
    for (const row of dayTrades) {
      const kind = premiumKind(row.premium_rate)
      if (!groups.has(kind)) groups.set(kind, [])
      groups.get(kind).push(row)
    }
    histogram.push({ time: date, value: dayTrades.length,
      color: groups.size > 1 ? COLORS.mixed : COLORS[[...groups.keys()][0]] || COLORS.unknown })
    // 当天没有真实 K 线时，不把成交标记错误吸附到前后交易日。
    if (!dailyByDate.has(date)) continue
    for (const [kind, rows] of groups) {
      markers.push({ id: `block-${date}-${kind}`, time: date,
        position: kind === 'discount' ? 'belowBar' : 'aboveBar',
        shape: kind === 'premium' ? 'arrowDown' : kind === 'discount' ? 'arrowUp' : 'circle',
        color: COLORS[kind], text: showLabels ? markerText(kind, rows) : '', size: 1,
      })
    }
  }
  return {
    dates, byDate, dailyByDate, markers, histogram,
    missingDates: [...byDate.keys()].filter(date => !dailyByDate.has(date)).sort(),
    candles: dates.map(time => {
      const row = dailyByDate.get(time)
      return row ? { time, open: row.open, high: row.high, low: row.low, close: row.close } : { time }
    }),
  }
}

export function createBlockOverviewOption(rows = []) {
  return {
    backgroundColor: 'transparent', animation: false,
    grid: { left: 64, right: 28, top: 44, bottom: 88 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: params => {
        const row = rows[params?.[0]?.dataIndex]
        return row ? `${row.trade_date}<br/>大宗交易：${row.count.toLocaleString('zh-CN')} 笔<br/>涉及证券：${row.stock_count.toLocaleString('zh-CN')} 只` : ''
      },
    },
    xAxis: { type: 'category', name: '日期', nameLocation: 'middle', nameGap: 28,
      data: rows.map(row => row.trade_date), axisLabel: { color: '#8b95a8', hideOverlap: true },
      axisLine: { lineStyle: { color: '#243044' } },
    },
    yAxis: { type: 'value', name: '大宗交易数量（笔）', min: 0, minInterval: 1,
      axisLabel: { color: '#8b95a8' }, splitLine: { lineStyle: { color: '#202938' } },
    },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 8, height: 24, borderColor: '#243044' }],
    series: [{ name: '大宗交易笔数', type: 'bar', data: rows.map(row => row.count),
      itemStyle: { color: '#5b9fd6', borderRadius: [3, 3, 0, 0] }, emphasis: { itemStyle: { color: '#93c5ed' } }, barMaxWidth: 22,
    }],
  }
}
