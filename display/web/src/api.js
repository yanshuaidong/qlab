async function parseJson(res) {
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(body.error || res.statusText)
  }
  return body
}

export async function getJson(url) {
  return parseJson(await fetch(url))
}

export async function sendJson(url, method, payload) {
  return parseJson(
    await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: payload == null ? undefined : JSON.stringify(payload),
    }),
  )
}

export function toTradeDate(time) {
  if (time == null) return ''
  if (typeof time === 'string') {
    if (/^\d{8}$/.test(time)) {
      return `${time.slice(0, 4)}-${time.slice(4, 6)}-${time.slice(6, 8)}`
    }
    return time.slice(0, 10)
  }
  if (typeof time === 'number') {
    const d = new Date(time * 1000)
    const y = d.getUTCFullYear()
    const m = String(d.getUTCMonth() + 1).padStart(2, '0')
    const day = String(d.getUTCDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  }
  if (typeof time === 'object' && time.year != null) {
    const m = String(time.month).padStart(2, '0')
    const d = String(time.day).padStart(2, '0')
    return `${time.year}-${m}-${d}`
  }
  return ''
}

export function toChartTime(dateStr) {
  return dateStr
}

export function flowColor(value) {
  if (value == null || Number.isNaN(value)) return '#5b6b82'
  return value >= 0 ? '#ef5350' : '#26a69a'
}

export function pctClass(value) {
  if (value == null || Number.isNaN(value)) return ''
  return value >= 0 ? 'up' : 'down'
}

export function formatNumber(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  })
}

export function formatPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${Number(value).toFixed(2)}%`
}

export function formatMarketCapYi(totalMvWan) {
  const yi = Number(totalMvWan) / 10000
  if (!Number.isFinite(yi) || yi <= 0) return ''
  const digits = yi >= 100 ? 0 : yi >= 10 ? 1 : 2
  return `${Number(yi.toFixed(digits))}亿`
}

export function formatAmount(value, unit) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  const abs = Math.abs(n)
  if (unit === '元') {
    if (abs >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`
    if (abs >= 1e4) return `${(n / 1e4).toFixed(2)} 万`
    return `${formatNumber(n, 0)} 元`
  }
  if (unit === '万元') {
    if (abs >= 1e4) return `${(n / 1e4).toFixed(2)} 亿`
    return `${formatNumber(n, 2)} 万`
  }
  if (unit === '亿元') {
    return `${formatNumber(n, 2)} 亿`
  }
  if (unit === '百万元') {
    if (abs >= 100) return `${(n / 100).toFixed(2)} 亿`
    return `${formatNumber(n, 2)} 百万`
  }
  return `${formatNumber(n, 2)} ${unit || ''}`.trim()
}

export function debounce(fn, wait = 200) {
  let timer = null
  return (...args) => {
    clearTimeout(timer)
    timer = setTimeout(() => fn(...args), wait)
  }
}
