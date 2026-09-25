import { toTradeDate } from '../api.js'

// 保留完整历史供拖动浏览；默认视窗只定位到信号前后，优先展示后续走势。
export function buildSignalKline(rawRows, signal) {
  const byDate = new Map()
  for (const row of rawRows) {
    const date = toTradeDate(row.trade_date)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)
        || !['open', 'high', 'low', 'close'].every(key => Number.isFinite(row[key]))) continue
    byDate.set(date, { ...row, trade_date: date })
  }
  const rows = [...byDate.values()].sort((a, b) => a.trade_date.localeCompare(b.trade_date))
  const signalIndex = rows.findIndex(row => row.trade_date === signal.trade_date)
  const nextIndex = rows.findIndex(row => row.trade_date >= signal.trade_date)
  const anchor = signalIndex >= 0 ? signalIndex : nextIndex >= 0 ? nextIndex : rows.length - 1
  const good = signal.mark_type === 'correct'
  return {
    rows,
    signalIndex,
    subsequentDays: rows.filter(row => row.trade_date > signal.trade_date).length,
    candles: rows.map(row => ({ time: row.trade_date, open: row.open, high: row.high, low: row.low, close: row.close })),
    markers: signalIndex < 0 ? [] : [{
      id: String(signal.id),
      time: signal.trade_date,
      position: good ? 'belowBar' : 'aboveBar',
      shape: good ? 'arrowUp' : 'arrowDown',
      color: good ? '#ffd54f' : '#ff3dce',
      text: `${signal.trade_date} ${good ? '好信号' : '差信号'}`,
      size: 1.5,
    }],
    range: rows.length ? {
      from: Math.max(-1, anchor - 20),
      to: Math.max(Math.min(rows.length - 1, anchor + 80) + 3, Math.max(-1, anchor - 20) + 10),
    } : null,
  }
}
