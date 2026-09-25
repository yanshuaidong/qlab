import { createHash } from 'node:crypto'

export const SMALL_SAMPLE_THRESHOLD = 5

export function normalizeLabel(value) {
  return typeof value === 'string' ? value.normalize('NFKC').trim().replace(/\s+/gu, ' ') : ''
}

function hasTable(db, name) {
  return Boolean(db.prepare("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?").get(name))
}

// 一次查询读取信号及标签快照；后续榜单、明细和搜索共用同一有效性判断。
// 本模块只执行 SELECT，不修复、不覆盖原始标签或人工标记。
export function readTagSnapshot(db) {
  const taggingAvailable = hasTable(db, 'trend_mark_tagging')
  const rows = db.prepare(taggingAvailable ? `
    SELECT t.id, t.ts_code, t.trade_date, t.mark_type, t.reason,
           g.trend_mark_id, g.ts_code AS tag_code, g.trade_date AS tag_date,
           g.reason_snapshot, g.reason_sha256, g.tags_json, g.tag_count
    FROM trend_mark t LEFT JOIN trend_mark_tagging g ON g.trend_mark_id = t.id
    ORDER BY t.trade_date DESC, t.id DESC
  ` : `SELECT id, ts_code, trade_date, mark_type, reason FROM trend_mark
       ORDER BY trade_date DESC, id DESC`).all()
  const tags = new Map()
  const excluded = { missing: 0, stale: 0, invalid: 0 }
  let validCorrect = 0
  let validFail = 0
  for (const row of rows) {
    if (row.trend_mark_id == null) {
      excluded.missing++
      continue
    }
    if (row.ts_code !== row.tag_code || row.trade_date !== row.tag_date || row.reason !== row.reason_snapshot) {
      excluded.stale++
      continue
    }
    const reason = row.reason || ''
    let parsed
    try { parsed = JSON.parse(row.tags_json) } catch { parsed = null }
    if (!['correct', 'fail'].includes(row.mark_type) || !reason.trim()
      || /^(初筛|标注失败)/u.test(reason.trimStart())
      || row.reason_sha256 !== createHash('sha256').update(reason).digest('hex')
      || !Array.isArray(parsed) || parsed.length !== row.tag_count
      || parsed.length < 10 || parsed.length > 30
      || parsed.some(tag => !tag || typeof tag.name !== 'string'
        || [...tag.name.trim()].length < 2 || [...tag.name.trim()].length > 24
        || !normalizeLabel(tag.name) || /[\r\n]/u.test(tag.name)
        || typeof tag.evidence !== 'string' || tag.evidence.trim().length < 2
        || !reason.includes(tag.evidence))) {
      excluded.invalid++
      continue
    }
    if (row.mark_type === 'correct') validCorrect++
    else validFail++
    // 同一信号重复标签只计一次，保留其不同的原文依据供核对。
    const signalTags = new Map()
    for (const tag of parsed) {
      const label = normalizeLabel(tag.name)
      if (!signalTags.has(label)) signalTags.set(label, new Set())
      signalTags.get(label).add(tag.evidence)
    }
    for (const [label, evidence] of signalTags) {
      if (!tags.has(label)) tags.set(label, { label, correctCount: 0, failCount: 0, signals: [] })
      const tag = tags.get(label)
      tag[row.mark_type === 'correct' ? 'correctCount' : 'failCount']++
      tag.signals.push({ id: row.id, ts_code: row.ts_code, trade_date: row.trade_date,
        mark_type: row.mark_type, reason, evidence: [...evidence] })
    }
  }
  for (const tag of tags.values()) {
    tag.totalCount = tag.correctCount + tag.failCount
    tag.correctRate = validCorrect ? tag.correctCount / validCorrect : null
    tag.failRate = validFail ? tag.failCount / validFail : null
    tag.correctShare = tag.totalCount ? tag.correctCount / tag.totalCount : null
    tag.smallSample = tag.totalCount < SMALL_SAMPLE_THRESHOLD
  }
  return {
    tags,
    summary: { totalSignals: rows.length, validCorrect, validFail,
      excludedCount: rows.length - validCorrect - validFail, excluded,
      uniqueLabels: tags.size, taggingAvailable, smallSampleThreshold: SMALL_SAMPLE_THRESHOLD },
  }
}

export function publicTag(tag) {
  const { signals, ...item } = tag
  return item
}

export function rankTags(snapshot, { group = 'correct', query = '', minCount = 1, page = 1, pageSize = 20 } = {}) {
  const field = group === 'correct' ? 'correctCount' : 'failCount'
  const needle = normalizeLabel(query).toLocaleLowerCase('zh-CN')
  const items = [...snapshot.tags.values()]
    .filter(tag => tag[field] > 0 && tag.totalCount >= minCount
      && tag.label.toLocaleLowerCase('zh-CN').includes(needle))
    .sort((a, b) => b[field] - a[field] || b.totalCount - a.totalCount || a.label.localeCompare(b.label, 'zh-CN'))
  return { total: items.length, page, pageSize,
    items: items.slice((page - 1) * pageSize, page * pageSize).map(publicTag) }
}

export function tagSignals(db, snapshot, label, { page = 1, pageSize = 20 } = {}) {
  const tag = snapshot.tags.get(normalizeLabel(label))
  const signals = tag?.signals || []
  const names = hasTable(db, 'moneyflow_dc') ? db.prepare(`
    SELECT name FROM moneyflow_dc WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 1
  `) : null
  return { label: normalizeLabel(label), total: signals.length, page, pageSize,
    items: signals.slice((page - 1) * pageSize, page * pageSize)
      .map(signal => ({ ...signal, name: names?.get(signal.ts_code)?.name || '' })) }
}
