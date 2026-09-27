import assert from 'node:assert/strict'
import test from 'node:test'
import { orderCandleMarkers } from '../../web/src/utils/kline-markers.js'

test('同一天的标记从近到远叠放，宗在游外侧', () => {
  const ordered = orderCandleMarkers([
    { id: 'block', time: '2026-06-04', text: '宗', stack: 2 },
    { id: 'hm', time: '2026-06-04', text: '游', stack: 1 },
    { id: 'reason', time: '2026-06-04', text: '败', stack: 0 },
    { id: 'next', time: '2026-06-05', text: '宗', stack: 2 },
  ])
  assert.deepEqual(ordered.map((item) => item.text), ['败', '游', '宗', '宗'])
  assert.equal('stack' in ordered[0], false)
})
