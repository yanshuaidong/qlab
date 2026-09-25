import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
import { REPO_ROOT } from './db.js'

function canonicalPath(value) {
  let resolved = path.resolve(REPO_ROOT, value)
  try { resolved = fs.realpathSync.native(resolved) } catch { /* 路径尚不存在时保留规范绝对路径。 */ }
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}

export class VectorService {
  constructor({ env = process.env, spawnWorker = spawn } = {}) {
    this.env = env
    this.spawnWorker = spawnWorker
    this.indexPath = path.resolve(REPO_ROOT, env.REASON_VECTOR_INDEX_PATH || 'storage/stock/reason_vectors')
    this.child = null
    this.pending = new Map()
    this.nextId = 0
    this.refreshing = false
    this.lastError = null
  }

  status(labels) {
    const configured = Boolean(this.env.REASON_VECTOR_MODEL_PATH && this.env.REASON_VECTOR_MODEL_VERSION)
    const base = { initialized: false, configured, state: 'uninitialized', refreshing: this.refreshing,
      lastError: this.lastError, updatedAt: null, indexedCount: 0, missingCount: labels.length,
      obsoleteCount: 0, modelId: 'BAAI/bge-m3', modelVersion: this.env.REASON_VECTOR_MODEL_VERSION || null }
    let manifest
    try {
      manifest = JSON.parse(fs.readFileSync(path.join(this.indexPath, 'manifest.json'), 'utf8'))
      if (manifest.schemaVersion !== 1 || !Array.isArray(manifest.labels)
        || !manifest.labels.every(label => typeof label === 'string') || !manifest.collection) {
        throw new Error('索引元数据格式无效，请刷新标签索引')
      }
    } catch (error) {
      return error.code === 'ENOENT' ? base : { ...base, state: 'error', lastError: error.message }
    }
    const indexed = new Set(manifest.labels)
    const current = new Set(labels)
    const missingCount = labels.filter(label => !indexed.has(label)).length
    const obsoleteCount = [...indexed].filter(label => !current.has(label)).length
    const matches = configured && manifest.modelId === 'BAAI/bge-m3' && manifest.dimensions === 1024
      && manifest.modelVersion === this.env.REASON_VECTOR_MODEL_VERSION
      && canonicalPath(manifest.modelPath || '') === canonicalPath(this.env.REASON_VECTOR_MODEL_PATH)
    return { ...base, initialized: true, updatedAt: manifest.updatedAt, indexedCount: indexed.size,
      missingCount, obsoleteCount, state: !matches ? 'incompatible' : missingCount || obsoleteCount ? 'stale' : 'ready' }
  }

  request(action, payload) {
    if (this.pending.size >= 8) return Promise.reject(new Error('向量服务繁忙，请稍后重试'))
    if (!this.child) {
      const child = this.spawnWorker(this.env.REASON_VECTOR_PYTHON || 'python',
        ['-u', path.join(REPO_ROOT, 'research/stock/reason_vector/worker.py')],
        { cwd: REPO_ROOT, env: { ...this.env, PYTHONIOENCODING: 'utf-8',
          REASON_VECTOR_INDEX_PATH: this.indexPath }, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true })
      this.child = child
      let stderr = ''
      child.stderr.setEncoding('utf8')
      child.stderr.on('data', chunk => {
        stderr = (stderr + chunk).slice(-4000)
        console.error(`[原因向量] ${chunk.trimEnd()}`)
      })
      const fail = message => {
        if (this.child !== child) return
        this.child = null
        child.kill()
        for (const pending of this.pending.values()) {
          clearTimeout(pending.timer)
          pending.reject(new Error(message))
        }
        this.pending.clear()
      }
      child.on('error', error => fail(`无法启动向量服务：${error.message}。请检查 REASON_VECTOR_PYTHON。`))
      child.stdin.on('error', error => fail(`向量服务通信失败：${error.message}`))
      child.on('exit', code => fail(`向量服务已退出（${code}）${stderr ? `：${stderr}` : ''}`))
      const lines = createInterface({ input: child.stdout })
      lines.on('line', line => {
        let response
        try { response = JSON.parse(line) } catch { return }
        const pending = this.pending.get(response.id)
        if (!pending) return
        clearTimeout(pending.timer)
        this.pending.delete(response.id)
        if (response.error) pending.reject(new Error(response.error))
        else pending.resolve(response.result)
      })
    }
    return new Promise((resolve, reject) => {
      const id = ++this.nextId
      const timer = setTimeout(() => {
        this.close('向量操作超时，已停止进程；请检查模型配置后重试')
      }, action === 'refresh' ? 30 * 60_000 : 5 * 60_000)
      this.pending.set(id, { resolve, reject, timer })
      this.child.stdin.write(`${JSON.stringify({ id, action, ...payload })}\n`)
    })
  }

  refresh(labels) {
    if (this.refreshing || this.pending.size) throw new Error('向量服务正在处理请求，请稍后刷新')
    this.refreshing = true
    this.lastError = null
    // 长时间模型加载/建索引在独立进程完成，HTTP 立即返回并由状态接口报告结果。
    this.request('refresh', { labels }).catch(error => {
      this.lastError = error.message
    }).finally(() => { this.refreshing = false })
  }

  async search(payload) {
    if (this.refreshing) throw new Error('标签索引正在刷新，请稍后搜索')
    return this.request('search', payload)
  }

  close(message = '向量服务已关闭') {
    const child = this.child
    this.child = null
    child?.kill()
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer)
      pending.reject(new Error(message))
    }
    this.pending.clear()
  }
}
