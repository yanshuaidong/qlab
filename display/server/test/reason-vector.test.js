import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { once } from 'node:events'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'
import express from 'express'
import { readTagSnapshot, rankTags, tagSignals, normalizeLabel } from '../src/reason-tags.js'
import { createApiRouter } from '../src/routes.js'
import { VectorService } from '../src/reason-vector-service.js'

const reason = '需求增加，产品短缺，价格预期上涨。原文证据。'
const digest = text => createHash('sha256').update(text).digest('hex')
function fixture(t) {
  const db = new DatabaseSync(':memory:')
  t.after(() => db.close())
  db.exec(`CREATE TABLE trend_mark (id INTEGER PRIMARY KEY, ts_code TEXT, trade_date TEXT, mark_type TEXT, reason TEXT);
    CREATE TABLE trend_mark_tagging (trend_mark_id INTEGER PRIMARY KEY, ts_code TEXT, trade_date TEXT,
      reason_snapshot TEXT, reason_sha256 TEXT, tags_json TEXT, tag_count INTEGER);
    CREATE TABLE moneyflow_dc (ts_code TEXT, trade_date TEXT, name TEXT);
    INSERT INTO moneyflow_dc VALUES ('000001.SZ', '2026-09-01', '测试股票');`)
  function add(id, type, labels, options = {}) {
    const code = '000001.SZ'
    const date = `2026-09-${String(id).padStart(2, '0')}`
    db.prepare('INSERT INTO trend_mark VALUES (?, ?, ?, ?, ?)').run(id, code, date, type, reason)
    if (labels === null) return
    const tags = Array.from({ length: 10 }, (_, index) => ({ name: labels[index % labels.length], evidence: '原文证据' }))
    const values = { ts_code: code, trade_date: date, reason_snapshot: reason, reason_sha256: digest(reason), tags_json: JSON.stringify(tags), tag_count: 10, ...options }
    db.prepare('INSERT INTO trend_mark_tagging VALUES (?, ?, ?, ?, ?, ?, ?)').run(id,
      values.ts_code, values.trade_date, values.reason_snapshot, values.reason_sha256, values.tags_json, values.tag_count)
  }
  add(1, 'correct', ['供不应求', ' ＡＩ '])
  add(2, 'correct', ['供不应求', 'AI'])
  add(3, 'fail', ['供不应求', '产品已涨价'])
  add(4, 'fail', null)
  add(5, 'correct', ['过期标签'], { reason_snapshot: '旧原文' })
  add(6, 'correct', ['过期标签'], { ts_code: 'changed' })
  add(7, 'fail', ['过期标签'], { trade_date: '2000-01-01' })
  add(8, 'correct', ['损坏标签'], { tags_json: '{bad json' })
  add(9, 'fail', ['无依据标签'], { tags_json: JSON.stringify(Array(10).fill({ name: '无依据', evidence: '原文没有此句' })) })
  add(10, 'correct', ['损坏标签'], { reason_sha256: 'invalid' })
  add(11, 'correct', ['损坏标签'], { tag_count: 12 })
  return db
}

test('归一化仅统一基本格式，不合并不同表述', () => {
  assert.equal(normalizeLabel('　ＡＩ　产业  '), 'AI 产业')
  assert.notEqual(normalizeLabel('涨价预期'), normalizeLabel('产品已涨价'))
})

test('统计排除失效/损坏记录，同一信号标签去重，同股票不同日期分别计数', t => {
  const db = fixture(t)
  db.exec('PRAGMA query_only = ON')
  const snapshot = readTagSnapshot(db)
  assert.deepEqual(snapshot.summary, { totalSignals: 11, validCorrect: 2, validFail: 1,
    excludedCount: 8, excluded: { missing: 1, stale: 3, invalid: 4 }, uniqueLabels: 3,
    taggingAvailable: true, smallSampleThreshold: 5 })
  const tag = snapshot.tags.get('供不应求')
  assert.equal(tag.totalCount, 3)
  assert.equal(tag.correctCount, 2)
  assert.equal(tag.failCount, 1)
  assert.equal(tag.correctRate, 1)
  assert.equal(tag.failRate, 1)
  assert.equal(tag.correctShare, 2 / 3)
  assert.equal(tag.smallSample, true)
  assert.equal(snapshot.tags.get('AI').totalCount, 2)
})

test('榜单按对应组数量排序，过滤和分页不改变分母', t => {
  const snapshot = readTagSnapshot(fixture(t))
  const good = rankTags(snapshot)
  assert.equal(good.items[0].label, '供不应求')
  assert.equal(good.items.some(tag => 'signals' in tag), false)
  const bad = rankTags(snapshot, { group: 'fail' })
  assert.deepEqual(bad.items.map(tag => tag.label), ['供不应求', '产品已涨价'])
  assert.equal(rankTags(snapshot, { minCount: 3 }).total, 1)
  const filtered = rankTags(snapshot, { query: ' ＡＩ ', pageSize: 1 })
  assert.equal(filtered.total, 1)
  assert.equal(filtered.items[0].correctRate, 1)
  assert.equal(filtered.items[0].failRate, 0)
  assert.equal(rankTags(snapshot, { page: 2, pageSize: 1 }).items.length, 1)
})

test('组内分母为零返回 null，缺标签表返回完整空状态', t => {
  const db = fixture(t)
  db.prepare("UPDATE trend_mark SET mark_type = 'correct' WHERE id = 3").run()
  assert.equal(readTagSnapshot(db).tags.get('供不应求').failRate, null)
  db.exec('DROP TABLE trend_mark_tagging')
  const snapshot = readTagSnapshot(db)
  assert.equal(snapshot.summary.totalSignals, 11)
  assert.equal(snapshot.summary.excludedCount, 11)
  assert.equal(snapshot.summary.taggingAvailable, false)
  assert.equal(rankTags(snapshot).total, 0)
})

test('明细包含最新人工标记、完整 reason 和去重后的证据，支持分页', t => {
  const db = fixture(t)
  const data = tagSignals(db, readTagSnapshot(db), ' ＡＩ ', { page: 2, pageSize: 1 })
  assert.equal(data.total, 2)
  assert.equal(data.items[0].id, 1)
  assert.equal(data.items[0].name, '测试股票')
  assert.equal(data.items[0].reason, reason)
  assert.deepEqual(data.items[0].evidence, ['原文证据'])
  db.prepare("UPDATE trend_mark SET mark_type = 'fail' WHERE id = 1").run()
  assert.equal(readTagSnapshot(db).tags.get('AI').correctCount, 1)
  assert.equal(tagSignals(db, readTagSnapshot(db), '不存在').total, 0)
})

async function apiFixture(t, overrides = {}) {
  const db = fixture(t)
  const vectors = {
    status: () => ({ initialized: true, state: 'ready', indexedCount: 3, configured: true }),
    search: async () => ({ items: [{ label: 'AI', score: 0.6 }, { label: '供不应求', score: 0.9 }] }),
    refresh: () => {}, ...overrides,
  }
  const app = express()
  app.use(express.json())
  app.use('/api', createApiRouter(() => ({ db }), vectors))
  const server = app.listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections() }))
  const url = `http://127.0.0.1:${server.address().port}/api/reason-vector`
  const request = async (route, body) => {
    const response = await fetch(url + route, body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    return { status: response.status, data: await response.json() }
  }
  return { db, vectors, request }
}

test('HTTP 概览、榜单和明细复用统计；刷新只传去重标签', async t => {
  let refreshed
  const { request } = await apiFixture(t, { refresh: labels => { refreshed = labels } })
  assert.equal((await request('/overview')).data.summary.uniqueLabels, 3)
  assert.equal((await request('/ranking?group=fail')).data.items[0].label, '供不应求')
  assert.equal((await request('/signals?label=AI')).data.total, 2)
  assert.equal((await request('/refresh', {})).status, 202)
  assert.deepEqual(refreshed, ['AI', '产品已涨价', '供不应求'])
})

test('HTTP 校验空文案、非法数量、相似度及分页参数', async t => {
  const { request } = await apiFixture(t)
  for (const body of [{ text: '' }, { text: '短缺', limit: 0 }, { text: '短缺', limit: true }, { text: '短缺', limit: 2.5 },
    { text: '短缺', minScore: 2 }, { text: '短缺', minScore: '0.5' }, { text: {} }]) {
    assert.equal((await request('/search', body)).status, 400)
  }
  for (const route of ['/ranking?group=other', '/ranking?page=-1', '/ranking?minCount=0', '/signals?label=']) {
    assert.equal((await request(route)).status, 400)
  }
})

test('HTTP 搜索按相似度排序，忽略失效和重复标签，返回实时关联数量', async t => {
  let input
  const { db, request } = await apiFixture(t, { search: async payload => {
    input = payload
    db.prepare("UPDATE trend_mark SET reason = '原文修改' WHERE id = 1").run()
    return { items: [{ label: 'AI', score: 0.6 }, { label: '失效标签', score: 1 },
      { label: '供不应求', score: 0.9 }, { label: '供不应求', score: 0.8 }] }
  } })
  const response = await request('/search', { text: '短缺', limit: 20, minScore: 0.5 })
  assert.equal(response.status, 200)
  assert.deepEqual(response.data.items.map(row => row.label), ['供不应求', 'AI'])
  assert.equal(response.data.items[0].totalCount, 2)
  assert.equal(response.data.items[1].correctCount, 1)
  assert.equal(input.labels.length, 3)
})

test('HTTP 未初始化、版本不匹配、刷新中和缺依赖有明确错误', async t => {
  const { vectors, request } = await apiFixture(t)
  vectors.status = () => ({ initialized: false })
  assert.match((await request('/search', { text: '短缺' })).data.error, /初始化/)
  vectors.status = () => ({ initialized: true, state: 'incompatible' })
  assert.equal((await request('/search', { text: '短缺' })).status, 409)
  vectors.status = () => ({ initialized: true, refreshing: true })
  assert.equal((await request('/search', { text: '短缺' })).status, 409)
  vectors.status = () => ({ initialized: true, state: 'ready', indexedCount: 3 })
  vectors.search = async () => { throw new Error('缺少本地模型依赖') }
  assert.equal((await request('/search', { text: '短缺' })).status, 503)
  vectors.refresh = () => { throw new Error('正在刷新') }
  assert.equal((await request('/refresh', {})).status, 409)
})

test('HTTP 空索引不执行嵌入，仍允许频次榜查询', async t => {
  const { request } = await apiFixture(t, {
    status: () => ({ initialized: true, state: 'stale', indexedCount: 0 }),
    search: () => { throw new Error('不应调用') },
  })
  assert.deepEqual((await request('/search', { text: '短缺' })).data.items, [])
  assert.equal((await request('/ranking')).data.total, 2)
})

test('索引状态不依赖 Python 或模型包；检测增删标签、模型变更和损坏 manifest', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qlab-vector-status-'))
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }))
  const env = { REASON_VECTOR_INDEX_PATH: dir, REASON_VECTOR_MODEL_PATH: dir, REASON_VECTOR_MODEL_VERSION: 'test-revision' }
  const service = new VectorService({ env })
  assert.equal(service.status(['AI']).state, 'uninitialized')
  const manifest = { schemaVersion: 1, modelId: 'BAAI/bge-m3', modelVersion: 'test-revision', modelPath: dir,
    dimensions: 1024, collection: 'test', labels: ['AI'], updatedAt: '2026-09-25T00:00:00Z' }
  fs.writeFileSync(path.join(dir, 'manifest.json'), JSON.stringify(manifest))
  assert.equal(service.status(['AI']).state, 'ready')
  assert.equal(service.status(['新标签']).missingCount, 1)
  assert.equal(service.status(['新标签']).obsoleteCount, 1)
  assert.equal(service.status(['新标签']).state, 'stale')
  env.REASON_VECTOR_MODEL_VERSION = 'another-revision'
  assert.equal(service.status(['AI']).state, 'incompatible')
  fs.writeFileSync(path.join(dir, 'manifest.json'), 'bad json')
  assert.equal(service.status([]).state, 'error')
})

test('刷新异步失败可通过状态获取，刷新期间拒绝重复刷新和搜索', async () => {
  const service = new VectorService({ env: {} })
  let rejectRefresh
  service.request = () => new Promise((resolve, reject) => { rejectRefresh = reject })
  service.refresh(['AI'])
  assert.equal(service.refreshing, true)
  assert.throws(() => service.refresh(['AI']), /正在处理/)
  await assert.rejects(service.search({}), /正在刷新/)
  rejectRefresh(new Error('模型不存在'))
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(service.refreshing, false)
  assert.equal(service.status([]).lastError, '模型不存在')
})
