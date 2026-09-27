import assert from 'node:assert/strict'
import { once } from 'node:events'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'
import express from 'express'
import { createApiRouter } from '../src/routes.js'

function fixture(t, { block = true, daily = true } = {}) {
  const db = new DatabaseSync(':memory:')
  t.after(() => db.close())
  if (block) {
    db.exec(`
      CREATE TABLE block_trade (
        trade_date TEXT, record_no INTEGER, ts_code TEXT, price REAL, vol REAL,
        amount REAL, buyer TEXT, seller TEXT, updated_at TEXT,
        PRIMARY KEY (trade_date, record_no)
      );
      INSERT INTO block_trade VALUES
        ('2026-06-04', 2, '301188.SZ', 11, 4.8, 52.8, '买方乙', '卖方乙', 'now'),
        ('2026-06-04', 1, '301188.SZ', 9, 4.78, 43.02, '买方甲', '卖方甲', 'now'),
        ('2026-06-05', 1, '301188.SZ', NULL, 1, NULL, NULL, NULL, 'now'),
        ('2026-06-04', 3, '000001.SZ', 10, 1, 10, '买', '卖', 'now');
    `)
  }
  if (daily) {
    db.exec(`
      CREATE TABLE daily (
        ts_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL,
        PRIMARY KEY (ts_code, trade_date)
      );
      INSERT INTO daily VALUES
        ('301188.SZ', '2026-06-04', 10, 11, 9, 10),
        ('301188.SZ', '2026-06-05', 10, 11, 9, 0);
    `)
  }
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

test('个股大宗交易按日期和序号返回，并计算相对收盘的折溢价', async (t) => {
  const base = await listen(t, fixture(t))
  const body = await (await fetch(`${base}/block-trades/${encodeURIComponent('301188.SZ')}`)).json()
  assert.equal(body.unit.amount, '万元')
  assert.equal(body.unit.vol, '万股')
  assert.deepEqual(body.rows.map((row) => [row.trade_date, row.record_no, row.price, row.buyer]), [
    ['2026-06-04', 1, 9, '买方甲'],
    ['2026-06-04', 2, 11, '买方乙'],
    ['2026-06-05', 1, null, null],
  ])
  assert.ok(Math.abs(body.rows[0].premium_rate - -10) < 1e-9)
  assert.ok(Math.abs(body.rows[1].premium_rate - 10) < 1e-9)
  assert.equal(body.rows[2].premium_rate, null)
  assert.deepEqual((await (await fetch(`${base}/block-trades/600519.SH`)).json()).rows, [])
})

test('没有大宗交易表或日线时仍返回空折溢价，不报错', async (t) => {
  const missing = await listen(t, fixture(t, { block: false, daily: false }))
  const empty = await (await fetch(`${missing}/block-trades/301188.SZ`)).json()
  assert.deepEqual(empty.rows, [])

  const noDaily = await listen(t, fixture(t, { daily: false }))
  const rows = (await (await fetch(`${noDaily}/block-trades/301188.SZ`)).json()).rows
  assert.equal(rows.length, 3)
  assert.equal(rows[0].premium_rate, null)
  assert.equal(rows[0].close, null)
})
