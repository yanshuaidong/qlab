import assert from 'node:assert/strict'
import test from 'node:test'
import { buildSignalKline } from '../../web/src/utils/signal-kline.js'

const signal = { id: 10, trade_date: '2026-05-07', mark_type: 'correct' }
function candle(date, close = 11) {
  return { trade_date: date, open: 10, high: 12, low: 9, close }
}

test('K线按日期排序去重，只在信号准确日期添加标记，保留后续历史', () => {
  const model = buildSignalKline([
    candle('2026-05-08'), candle('2026-05-07', 10), candle('2026-05-06'), candle('2026-05-07', 12),
    candle('2026-05-09', null),
  ], signal)
  assert.deepEqual(model.rows.map(row => row.trade_date), ['2026-05-06', '2026-05-07', '2026-05-08'])
  assert.equal(model.candles[1].close, 12)
  assert.equal(model.signalIndex, 1)
  assert.equal(model.subsequentDays, 1)
  assert.equal(model.markers[0].time, signal.trade_date)
  assert.equal(model.markers[0].shape, 'arrowUp')
  assert.match(model.markers[0].text, /2026-05-07 好信号/)
  const bad = buildSignalKline([candle(signal.trade_date)], { ...signal, mark_type: 'fail' })
  assert.equal(bad.markers[0].shape, 'arrowDown')
  assert.match(bad.markers[0].text, /差信号/)
})

test('缺少信号当天行情不错误标记邻日，空行情和无后续行情可用', () => {
  const missing = buildSignalKline([candle('2026-05-06'), candle('2026-05-08')], signal)
  assert.equal(missing.signalIndex, -1)
  assert.deepEqual(missing.markers, [])
  assert.ok(missing.range)
  const empty = buildSignalKline([], signal)
  assert.equal(empty.range, null)
  assert.deepEqual(empty.markers, [])
  assert.equal(empty.subsequentDays, 0)
  const last = buildSignalKline([candle('2026-05-06'), candle('2026-05-07')], signal)
  assert.equal(last.subsequentDays, 0)
  assert.ok(last.range.to > last.range.from)
})

test('默认视窗为前20后80根K线，完整行情不受统计截止日期截断', () => {
  const rows = Array.from({ length: 240 }, (_, index) => {
    const date = new Date(Date.UTC(2026, 0, 1 + index)).toISOString().slice(0, 10)
    return candle(date)
  })
  const model = buildSignalKline(rows, { ...signal, trade_date: rows[40].trade_date })
  assert.equal(model.range.from, 20)
  assert.equal(model.range.to, 123)
  assert.equal(model.candles.length, 240)
  assert.equal(model.subsequentDays, 199)
})
