/**
 * 同一根 K 线上的标记按 stack 从近到远叠放：0 贴着 K 线，数字越大越靠外。
 * 之后新增标记时取下一个整数，并保持数组里同一天的标记连续。
 */
export function orderCandleMarkers(markers) {
  return markers
    .map((marker, index) => ({ marker, index }))
    .sort((a, b) => {
      if (a.marker.time < b.marker.time) return -1
      if (a.marker.time > b.marker.time) return 1
      const stackA = a.marker.stack ?? 0
      const stackB = b.marker.stack ?? 0
      if (stackA !== stackB) return stackA - stackB
      return a.index - b.index
    })
    .map(({ marker }) => {
      const { stack, ...rest } = marker
      return rest
    })
}
