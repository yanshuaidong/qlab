const BOARDS = {
  main: { key: 'main', char: '主', title: '主板' },
  star: { key: 'star', char: '科', title: '科创板' },
  chinext: { key: 'chinext', char: '创', title: '创业板' },
  bse: { key: 'bse', char: '北', title: '北交所' },
}

/** 按代码区分主板、科创板、创业板、北交所。B 股等其余代码不标记。 */
export function boardOf(tsCode) {
  const code = String(tsCode || '').trim().toUpperCase()
  const dot = code.lastIndexOf('.')
  if (dot <= 0) return null
  const symbol = code.slice(0, dot)
  const market = code.slice(dot + 1)
  if (!/^\d{6}$/.test(symbol)) return null
  if (market === 'BJ') return BOARDS.bse
  if (market === 'SH' && (symbol.startsWith('688') || symbol.startsWith('689'))) return BOARDS.star
  if (market === 'SZ' && symbol.startsWith('30')) return BOARDS.chinext
  if (market === 'SH' && symbol.startsWith('60')) return BOARDS.main
  if (market === 'SZ' && symbol.startsWith('00')) return BOARDS.main
  return null
}
