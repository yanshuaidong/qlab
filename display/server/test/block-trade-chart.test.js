import test from 'node:test'
import assert from 'node:assert/strict'
import { buildBlockTradeKline, createBlockOverviewOption, premiumKind, premiumLabel } from '../../web/src/utils/block-trade-chart.js'

const candle = { trade_date: '2026-09-14', open: 10, high: 12, low: 9, close: 10 }
const trade = { trade_date: '2026-09-14', price: 9, premium_rate: -10 }

test('折溢价分类保留缺价，不把 null 视为平价', () => {
  assert.equal(premiumKind(null), 'unknown')
  assert.equal(premiumKind(undefined), 'unknown')
  assert.equal(premiumKind(NaN), 'unknown')
  assert.equal(premiumKind(-10), 'discount')
  assert.equal(premiumKind(10), 'premium')
  assert.equal(premiumKind(0), 'flat')
  assert.equal(premiumLabel(-10), '折价 10.00%')
  assert.equal(premiumLabel(10), '溢价 10.00%')
  assert.equal(premiumLabel(null), '无法计算')
})

test('同日多笔成交逐笔保留，标记按折溢价类别汇总范围', () => {
  const trades = [trade, trade, { ...trade, premium_rate: -5 }, { ...trade, premium_rate: 3 }, { ...trade, premium_rate: 0 }]
  const model = buildBlockTradeKline([candle], trades)
  assert.equal(model.byDate.get(candle.trade_date).length, 5)
  assert.equal(model.histogram[0].value, 5)
  assert.equal(model.histogram[0].color, '#be8cf0')
  assert.equal(model.markers.length, 3)
  assert.equal(model.markers[0].text, '折 5.00~10.00% · 3笔')
  assert.equal(model.markers[0].position, 'belowBar')
  assert.equal(model.markers[1].text, '溢 3.00% · 1笔')
  assert.equal(model.markers[1].position, 'aboveBar')
})

test('缺 K 线的成交日保留时间和成交柱，绝不标注到相邻 K 线', () => {
  const missing = { ...trade, trade_date: '2026-09-15', premium_rate: null }
  const model = buildBlockTradeKline([candle], [missing])
  assert.deepEqual(model.dates, ['2026-09-14', '2026-09-15'])
  assert.deepEqual(model.candles[1], { time: '2026-09-15' })
  assert.deepEqual(model.missingDates, ['2026-09-15'])
  assert.deepEqual(model.markers, [])
  assert.equal(model.histogram[1].value, 1)
  assert.equal(model.histogram[0].value, 0)
})

test('只有成交、完全无行情时仍可浏览事件', () => {
  const model = buildBlockTradeKline([], [trade])
  assert.equal(model.histogram.length, 1)
  assert.equal(model.histogram[0].value, 1)
  assert.equal(model.dailyByDate.size, 0)
  assert.equal(model.markers.length, 0)
})

test('无效行情不生成蜡烛；排序去重行情，但不合并成交', () => {
  const model = buildBlockTradeKline([
    { ...candle, trade_date: '2026-09-16', open: null },
    { ...candle, trade_date: '2026-09-15' }, candle, candle,
  ], [{ ...trade, trade_date: '2026-09-16' }, trade, trade])
  assert.deepEqual(model.dates, ['2026-09-14', '2026-09-15', '2026-09-16'])
  assert.equal(model.dailyByDate.size, 2)
  assert.equal(model.byDate.get('2026-09-14').length, 2)
  assert.deepEqual(model.missingDates, ['2026-09-16'])
})

test('隐藏标注文字仍保留事件标记和成交数量', () => {
  const model = buildBlockTradeKline([candle], [trade], false)
  assert.equal(model.markers.length, 1)
  assert.equal(model.markers[0].text, '')
  assert.equal(model.histogram[0].value, 1)
})

test('全局柱状图纵轴为成交笔数而非股票只数，日期保持顺序', () => {
  const rows = [{ trade_date: '2026-09-14', count: 5, stock_count: 2 }, { trade_date: '2026-09-15', count: 7, stock_count: 3 }]
  const option = createBlockOverviewOption(rows)
  assert.deepEqual(option.xAxis.data, ['2026-09-14', '2026-09-15'])
  assert.deepEqual(option.series[0].data, [5, 7])
  assert.equal(option.yAxis.min, 0)
  assert.equal(option.yAxis.minInterval, 1)
  assert.match(option.tooltip.formatter([{ dataIndex: 0 }]), /大宗交易：5 笔/)
  assert.match(option.tooltip.formatter([{ dataIndex: 0 }]), /涉及证券：2 只/)
  assert.equal(createBlockOverviewOption().tooltip.formatter([]), '')
})
