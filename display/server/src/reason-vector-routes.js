import { Router } from 'express'
import { readTagSnapshot, rankTags, tagSignals, publicTag } from './reason-tags.js'

function integer(value, fallback, min, max, name) {
  if (value == null) return fallback
  const result = Number(value)
  if (!['number', 'string'].includes(typeof value)
    || value === '' || !Number.isInteger(result) || result < min || result > max) {
    const error = new Error(`${name} 必须是 ${min}～${max} 的整数`)
    error.status = 400
    throw error
  }
  return result
}

function text(value, fallback = '') {
  if (value == null) return fallback
  if (typeof value !== 'string') {
    const error = new Error('文本参数必须是字符串')
    error.status = 400
    throw error
  }
  return value.trim()
}

export function createReasonVectorRouter(vectors) {
  const router = Router()
  const endpoint = handler => (req, res, next) => Promise.resolve().then(() => handler(req, res)).catch(next)

  router.get('/overview', endpoint((req, res) => {
    const snapshot = readTagSnapshot(req.db)
    res.json({ summary: snapshot.summary, index: vectors.status([...snapshot.tags.keys()]) })
  }))

  router.get('/ranking', endpoint((req, res) => {
    const group = text(req.query.group, 'correct')
    if (!['correct', 'fail'].includes(group)) return res.status(400).json({ error: 'group 必须为 correct 或 fail' })
    const options = { group, query: text(req.query.q),
      minCount: integer(req.query.minCount, 1, 1, 1_000_000, '最少关联信号数'),
      page: integer(req.query.page, 1, 1, 1_000_000, '页码'),
      pageSize: integer(req.query.pageSize, 20, 1, 100, '每页数量') }
    const snapshot = readTagSnapshot(req.db)
    res.json({ ...rankTags(snapshot, options), summary: snapshot.summary })
  }))

  router.get('/signals', endpoint((req, res) => {
    const label = text(req.query.label)
    if (!label) return res.status(400).json({ error: '需要标签名称' })
    const options = { page: integer(req.query.page, 1, 1, 1_000_000, '页码'),
      pageSize: integer(req.query.pageSize, 20, 1, 100, '每页数量') }
    res.json(tagSignals(req.db, readTagSnapshot(req.db), label, options))
  }))

  router.post('/refresh', endpoint((req, res) => {
    const snapshot = readTagSnapshot(req.db)
    try { vectors.refresh([...snapshot.tags.keys()].sort()) }
    catch (error) { return res.status(409).json({ error: error.message }) }
    res.status(202).json({ index: vectors.status([...snapshot.tags.keys()]) })
  }))

  router.post('/search', endpoint(async (req, res) => {
    const query = text(req.body?.text)
    if (!query || query.length > 4000) return res.status(400).json({ error: '请输入 1～4000 字的搜索文案' })
    const limit = integer(req.body?.limit, 20, 1, 100, '返回数量')
    const minScore = req.body?.minScore == null || req.body.minScore === '' ? null : req.body.minScore
    if (minScore !== null && (typeof minScore !== 'number' || !Number.isFinite(minScore) || minScore < -1 || minScore > 1)) {
      return res.status(400).json({ error: '最低语义相似度必须在 -1～1 之间' })
    }
    let snapshot = readTagSnapshot(req.db)
    const status = vectors.status([...snapshot.tags.keys()])
    if (status.refreshing) return res.status(409).json({ error: '索引正在刷新，请稍后搜索' })
    if (!status.initialized) return res.status(409).json({ error: '标签向量索引尚未初始化，请先刷新标签索引' })
    if (['incompatible', 'error'].includes(status.state)) {
      return res.status(409).json({ error: status.lastError || '模型配置与索引不一致，请配置本地模型并刷新标签索引' })
    }
    if (!snapshot.tags.size || !status.indexedCount) return res.json({ items: [], index: status })
    let result
    try { result = await vectors.search({ text: query, limit, minScore, labels: [...snapshot.tags.keys()] }) }
    catch (error) { return res.status(503).json({ error: error.message }) }
    // 嵌入可能耗时；返回前重新读取，避免把计算期间失效的信号带回页面。
    snapshot = readTagSnapshot(req.db)
    const seen = new Set()
    const items = result.items.filter(item => {
      if (!snapshot.tags.has(item.label) || seen.has(item.label) || !Number.isFinite(item.score)
        || (minScore !== null && item.score < minScore)) return false
      seen.add(item.label)
      return true
    }).sort((a, b) => b.score - a.score).slice(0, limit)
      .map(item => ({ ...publicTag(snapshot.tags.get(item.label)), score: item.score }))
    res.json({ items, index: vectors.status([...snapshot.tags.keys()]) })
  }))

  router.use((error, req, res, _next) => {
    res.status(error.status || 500).json({ error: error.message || '原因向量服务错误' })
  })
  return router
}
