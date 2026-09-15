import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import cors from 'cors'
import express from 'express'

import { openDb } from './db.js'
import { createApiRouter } from './routes.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PORT = Number(process.env.PORT || 3001)
const distDir = path.resolve(__dirname, '../../web/dist')

let db = null
let dbPath = null
let dbError = null

try {
  const opened = openDb()
  db = opened.db
  dbPath = opened.dbPath
  console.log(`SQLite: ${dbPath}`)
} catch (err) {
  dbError = err.message
  console.error(dbError)
}

const app = express()
app.use(cors())
app.use(express.json())
app.set('json replacer', (_key, value) =>
  typeof value === 'bigint' ? Number(value) : value,
)

app.use(
  '/api',
  createApiRouter(() => ({ db, dbPath, error: dbError })),
)

if (fs.existsSync(distDir)) {
  app.use(express.static(distDir))
  app.get(/^\/(?!api).*/, (req, res) => {
    res.sendFile(path.join(distDir, 'index.html'))
  })
}

app.use((err, req, res, _next) => {
  console.error(err)
  res.status(500).json({ error: err.message || '服务器错误' })
})

app.listen(PORT, () => {
  console.log(`Express http://127.0.0.1:${PORT}`)
})
