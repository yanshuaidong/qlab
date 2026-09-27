import assert from 'node:assert/strict'
import { once } from 'node:events'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'
import express from 'express'
import { createApiRouter } from '../src/routes.js'

function fixture(t) {
  const db = new DatabaseSync(':memory:')
  t.after(() => db.close())
  db.exec(`
    CREATE TABLE moneyflow_dc (ts_code TEXT, trade_date TEXT, name TEXT);
    INSERT INTO moneyflow_dc VALUES
      ('300125.SZ', '2026-09-24', '聆达股份'),
      ('000001.SZ', '2026-09-24', '平安银行'),
      ('600000.SH', '2026-09-24', '*ST仍然');
    CREATE TABLE daily (ts_code TEXT, trade_date TEXT);
    INSERT INTO daily VALUES
      ('300125.SZ', '2026-08-10'),
      ('000010.SZ', '2026-07-02');
    CREATE TABLE stock_st (ts_code TEXT, trade_date TEXT, name TEXT);
    INSERT INTO stock_st VALUES
      ('300125.SZ', '2026-08-06', '*ST聆达'),
      ('600001.SH', '2026-08-07', '其他'),
      ('600001.SH', '2026-07-01', '其他'),
      ('600000.SH', '2026-06-01', '*ST仍然');
    CREATE TABLE st (
      ts_code TEXT, name TEXT, pub_date TEXT, imp_date TEXT,
      st_type TEXT, st_reason TEXT, st_explain TEXT
    );
    INSERT INTO st VALUES
      ('300125.SZ', '聆达股份', '2026-08-06', '2026-08-07', '撤销*ST', '撤销退市风险警示', ''),
      ('300125.SZ', '*ST聆达', '2026-01-27', '2026-01-28', '撤销叠加*ST', '只撤销一层', ''),
      ('000010.SZ', '美丽生态', '2026-07-01', '2026-07-01', '撤销ST', '撤销其他风险警示', ''),
      ('600000.SH', '仍然股份', '2026-06-01', '2026-06-01', '撤销*ST', '当天仍在名单', ''),
      ('000011.SZ', '退市华嵘', '2026-06-01', '2026-06-01', '退市整理期', '终止上市', ''),
      ('300096.SZ', '易联众', '2026-09-27', '2026-09-28', '撤销ST', '实施日尚未到来', '');
  `)
  return db
}

async function listen(t, db) {
  const app = express()
  app.use('/api', createApiRouter(() => ({ db, dbPath: ':memory:' }), {}))
  const server = app.listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(() => new Promise((resolve, reject) => {
    server.close((err) => (err ? reject(err) : resolve()))
    server.closeAllConnections()
  }))
  return `http://127.0.0.1:${server.address().port}/api`
}

test('摘帽只保留整段撤销且实施日已离开 ST 名单的记录', async (t) => {
  const base = await listen(t, fixture(t))
  const listed = await (await fetch(`${base}/st-uncap/300125.SZ`)).json()
  assert.deepEqual(listed.rows.map((row) => [row.trade_date, row.imp_date, row.st_type]), [
    ['2026-08-10', '2026-08-07', '撤销*ST'],
  ])
  const snapped = await (await fetch(`${base}/st-uncap/000010.SZ`)).json()
  assert.equal(snapped.rows[0].trade_date, '2026-07-02')
  assert.deepEqual((await (await fetch(`${base}/st-uncap/600000.SH`)).json()).rows, [])
  assert.deepEqual((await (await fetch(`${base}/st-uncap/000011.SZ`)).json()).rows, [])
  assert.deepEqual((await (await fetch(`${base}/st-uncap/300096.SZ`)).json()).rows, [])
})

test('股票列表可按有摘帽记录筛选', async (t) => {
  const base = await listen(t, fixture(t))
  const all = await (await fetch(`${base}/stocks`)).json()
  assert.deepEqual(all.items.map((item) => item.ts_code), ['000001.SZ', '300125.SZ', '600000.SH'])
  const uncap = await (await fetch(`${base}/stocks?uncap=1`)).json()
  assert.deepEqual(uncap.items.map((item) => item.ts_code), ['300125.SZ'])
  assert.equal((await fetch(`${base}/stocks?uncap=2`)).status, 400)
})

test('没有 ST 变更表时摘帽筛选和明细为空', async (t) => {
  const db = new DatabaseSync(':memory:')
  t.after(() => db.close())
  db.exec(`CREATE TABLE moneyflow_dc (ts_code TEXT, trade_date TEXT, name TEXT);
    INSERT INTO moneyflow_dc VALUES ('000001.SZ', '2026-09-24', '平安银行');`)
  const base = await listen(t, db)
  assert.deepEqual((await (await fetch(`${base}/stocks?uncap=1`)).json()).items, [])
  assert.deepEqual((await (await fetch(`${base}/st-uncap/000001.SZ`)).json()).rows, [])
  assert.equal((await (await fetch(`${base}/stocks`)).json()).items.length, 1)
})
