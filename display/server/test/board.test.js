import assert from 'node:assert/strict'
import test from 'node:test'
import { boardOf } from '../../web/src/utils/board.js'

test('按代码区分主板、科创板、创业板、北交所', () => {
  assert.equal(boardOf('600519.SH').char, '主')
  assert.equal(boardOf('601318.SH').title, '主板')
  assert.equal(boardOf('603259.SH').key, 'main')
  assert.equal(boardOf('605117.SH').char, '主')
  assert.equal(boardOf('000001.SZ').char, '主')
  assert.equal(boardOf('001979.SZ').char, '主')
  assert.equal(boardOf('002594.SZ').char, '主')
  assert.equal(boardOf('003816.SZ').char, '主')
  assert.equal(boardOf('688981.SH').char, '科')
  assert.equal(boardOf('689009.SH').title, '科创板')
  assert.equal(boardOf('300750.SZ').char, '创')
  assert.equal(boardOf('301236.SZ').char, '创')
  assert.equal(boardOf('302132.SZ').title, '创业板')
  assert.equal(boardOf('920000.BJ').char, '北')
  assert.equal(boardOf('830799.BJ').title, '北交所')
  assert.equal(boardOf('600519.sh').char, '主')
})

test('B 股和无法识别的代码不标记', () => {
  assert.equal(boardOf('900901.SH'), null)
  assert.equal(boardOf('200011.SZ'), null)
  assert.equal(boardOf('201872.SZ'), null)
  assert.equal(boardOf(''), null)
  assert.equal(boardOf('600519'), null)
})
