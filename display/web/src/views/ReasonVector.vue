<template>
  <section class="page reason-vector-page">
    <div class="toolbar">
      <h2>原因向量</h2>
      <el-button :loading="overviewLoading" @click="reload">更新统计</el-button>
      <el-button type="primary" :loading="index.refreshing" :disabled="refreshStarting || searching" @click="refreshIndex">刷新标签索引</el-button>
    </div>
    <el-alert title="仅供历史数据探索。高频不代表预测能力或因果关系；语义相似度不是上涨概率，也不是成功率。"
      type="info" :closable="false" show-icon />
    <el-alert v-if="overviewError" :title="overviewError" type="error" :closable="false" show-icon />
    <div v-if="summary" class="summary-grid">
      <div><span>当前信号总数</span><strong>{{ summary.totalSignals }}</strong></div>
      <div><span>有效标签 · 好信号</span><strong>{{ summary.validCorrect }}</strong></div>
      <div><span>有效标签 · 差信号</span><strong>{{ summary.validFail }}</strong></div>
      <div><span>未纳入数量</span><strong>{{ summary.excludedCount }}</strong></div>
      <div><span>去重标签数</span><strong>{{ summary.uniqueLabels }}</strong></div>
    </div>
    <div v-if="summary" class="hint-text">
      未纳入：无标签 {{ summary.excluded.missing }}，代码／日期／reason 已变化 {{ summary.excluded.stale }}，无效记录 {{ summary.excluded.invalid }}。
      <span v-if="!summary.taggingAvailable">尚未建立标签表，请先运行标签提取。</span>
    </div>
    <div class="index-status">
      <el-tag :type="index.state === 'ready' ? 'success' : 'warning'">{{ indexMessage }}</el-tag>
      <span>索引更新时间：{{ formatTime(index.updatedAt) }}</span>
      <span>已索引 {{ index.indexedCount || 0 }} 个标签</span>
      <span v-if="index.modelVersion">模型：{{ index.modelId }} / {{ index.modelVersion }}</span>
    </div>
    <el-alert v-if="!index.configured" title="向量搜索需配置本地 BGE-M3 模型路径和固定版本；未配置时仍可使用频次榜和信号明细。详见 research/stock/reason_vector/README.md。"
      type="warning" :closable="false" />
    <el-alert v-if="index.lastError" :title="`索引操作失败：${index.lastError}`" type="error" :closable="false" show-icon />

    <section class="vector-panel">
      <h3>相似标签搜索</h3>
      <form class="search-form" @submit.prevent="search">
        <el-input v-model="query" type="textarea" :rows="2" :maxlength="4000" show-word-limit
          placeholder="例如：产品短缺，后面可能涨价" aria-label="搜索文案" />
        <div class="toolbar">
          <label>返回数量 <el-input-number v-model="limit" :min="1" :max="100" :precision="0" size="small" /></label>
          <el-checkbox v-model="useMinScore">最低语义相似度</el-checkbox>
          <el-input-number v-if="useMinScore" v-model="minScore" :min="-1" :max="1" :step="0.05" :precision="3" size="small" aria-label="最低语义相似度" />
          <el-button native-type="submit" type="primary" :loading="searching" :disabled="!query.trim() || !canSearch">搜索</el-button>
        </div>
      </form>
      <p class="hint-text">按标签名称的余弦相似度降序排列，好坏标记和出现频次不参与排序。点击标签或左侧箭头展开信号。</p>
      <el-alert v-if="searchError" :title="searchError" type="error" :closable="false" show-icon />
      <el-table ref="searchTable" :data="searchItems" row-key="label" v-loading="searching" :empty-text="searchEmptyText">
        <el-table-column type="expand"><template #default="{ row }"><ReasonTagSignals :label="row.label" /></template></el-table-column>
        <el-table-column type="index" label="排名" width="65" />
        <el-table-column prop="label" label="标签名称" min-width="180"><template #default="{ row }">
          <el-button link type="primary" @click="searchTable?.toggleRowExpansion(row)">{{ row.label }}</el-button>
        </template></el-table-column>
        <el-table-column label="语义相似度" width="140"><template #default="{ row }">{{ row.score.toFixed(6) }}</template></el-table-column>
        <el-table-column prop="totalCount" label="关联信号总数" min-width="130" />
        <el-table-column prop="correctCount" label="好信号数" min-width="100" />
        <el-table-column prop="failCount" label="差信号数" min-width="100" />
      </el-table>
    </section>

    <section class="vector-panel">
      <h3>好／差信号标签频次榜</h3>
      <form class="toolbar" @submit.prevent="applyFilter">
        <el-input v-model="filter" placeholder="按标签名称筛选" clearable class="tag-filter" aria-label="标签名称筛选" />
        <label>最少关联信号数 <el-input-number v-model="minCount" :min="1" :max="1000000" :precision="0" size="small" /></label>
        <el-button native-type="submit">筛选</el-button>
      </form>
      <el-tabs v-model="group" @tab-change="changeGroup">
        <el-tab-pane label="好信号高频标签榜" name="correct" />
        <el-tab-pane label="差信号高频标签榜" name="fail" />
      </el-tabs>
      <p class="hint-text">组内出现率以全部有有效标签的该组信号为分母，不随标签筛选变化。每条信号可有多个标签，出现率之和可以超过 100%。关联信号少于 {{ summary?.smallSampleThreshold || 5 }} 条提示“样本较少”。</p>
      <el-alert v-if="rankingError" :title="rankingError" type="error" :closable="false" show-icon />
      <el-table :key="rankingKey" ref="rankingTable" :data="rankingItems" row-key="label" v-loading="rankingLoading" empty-text="暂无符合条件的有效标签">
        <el-table-column type="expand"><template #default="{ row }"><ReasonTagSignals :label="row.label" /></template></el-table-column>
        <el-table-column label="标签名称" min-width="200"><template #default="{ row }">
          <el-button link type="primary" @click="rankingTable?.toggleRowExpansion(row)">{{ row.label }}</el-button>
          <el-tag v-if="row.smallSample" type="warning" size="small" class="sample-tag">样本较少</el-tag>
        </template></el-table-column>
        <el-table-column prop="correctCount" label="好信号数" width="100" />
        <el-table-column label="好信号组内出现率" min-width="155"><template #default="{ row }">{{ percent(row.correctRate) }}</template></el-table-column>
        <el-table-column prop="failCount" label="差信号数" width="100" />
        <el-table-column label="差信号组内出现率" min-width="155"><template #default="{ row }">{{ percent(row.failRate) }}</template></el-table-column>
        <el-table-column prop="totalCount" label="关联信号总数" min-width="125" />
        <el-table-column label="标签关联信号中的好信号占比" min-width="230"><template #default="{ row }">{{ percent(row.correctShare) }}</template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="20" :total="rankingTotal"
        layout="total, prev, pager, next" @current-change="loadRanking" />
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getJson, sendJson } from '../api.js'
import ReasonTagSignals from '../components/ReasonTagSignals.vue'

const summary = ref(null)
const index = ref({ state: 'uninitialized', configured: true })
const overviewLoading = ref(false)
const overviewError = ref('')
const refreshStarting = ref(false)
const query = ref('')
const limit = ref(20)
const minScore = ref(0.5)
const useMinScore = ref(false)
const searching = ref(false)
const searched = ref(false)
const searchItems = ref([])
const searchError = ref('')
const searchTable = ref(null)
const filter = ref('')
const minCount = ref(1)
let appliedFilter = { q: '', minCount: 1 }
const group = ref('correct')
const page = ref(1)
const rankingItems = ref([])
const rankingTotal = ref(0)
const rankingLoading = ref(false)
const rankingError = ref('')
const rankingTable = ref(null)
const rankingKey = ref(0)
let rankingRequest = 0
let overviewRequest = 0
let searchRequest = 0
let pollTimer
let disposed = false
const canSearch = computed(() => index.value.initialized && !index.value.refreshing && !refreshStarting.value
  && ['ready', 'stale'].includes(index.value.state))
const indexMessage = computed(() => {
  if (index.value.refreshing) return '索引刷新中，统计和明细仍可使用'
  if (index.value.state === 'ready') return '索引已同步'
  if (index.value.state === 'stale') return `索引待同步：新增 ${index.value.missingCount}，失效 ${index.value.obsoleteCount}（搜索自动过滤失效标签）`
  if (index.value.state === 'incompatible') return '模型配置已变化或未配置，需要刷新整个索引'
  if (index.value.state === 'error') return '索引读取失败，请刷新索引'
  return '尚未初始化，请配置本地模型后刷新标签索引'
})
const searchEmptyText = computed(() => {
  if (!index.value.initialized) return '标签向量索引尚未初始化'
  if (!index.value.indexedCount) return '索引没有标签记录'
  return searched.value ? '没有符合相似度条件的标签' : '输入文案后点击搜索'
})
function percent(value) { return value == null ? '暂无数据' : `${(value * 100).toFixed(2)}%` }
function formatTime(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未建立' }

async function loadOverview() {
  const id = ++overviewRequest
  overviewLoading.value = true
  overviewError.value = ''
  clearTimeout(pollTimer)
  try {
    const data = await getJson('/api/reason-vector/overview')
    if (disposed || id !== overviewRequest) return
    const wasRefreshing = index.value.refreshing
    summary.value = data.summary
    index.value = data.index
    if (index.value.refreshing) pollTimer = setTimeout(loadOverview, 2000)
    else if (wasRefreshing) loadRanking()
  } catch (err) {
    if (disposed || id !== overviewRequest) return
    overviewError.value = err.message
    if (index.value.refreshing) pollTimer = setTimeout(loadOverview, 5000)
  } finally {
    if (id === overviewRequest) overviewLoading.value = false
  }
}
async function loadRanking() {
  const id = ++rankingRequest
  rankingLoading.value = true
  rankingError.value = ''
  rankingItems.value = []
  rankingKey.value++
  try {
    const data = await getJson(`/api/reason-vector/ranking?${new URLSearchParams({ ...appliedFilter, group: group.value, page: page.value, pageSize: 20 })}`)
    if (disposed || id !== rankingRequest) return
    rankingItems.value = data.items
    rankingTotal.value = data.total
    summary.value = data.summary
  } catch (err) {
    if (id === rankingRequest && !disposed) rankingError.value = err.message
  } finally {
    if (id === rankingRequest) rankingLoading.value = false
  }
}
function applyFilter() {
  appliedFilter = { q: filter.value, minCount: minCount.value ?? 1 }
  page.value = 1
  loadRanking()
}
function changeGroup() { page.value = 1; loadRanking() }
function clearSearch() { searchRequest++; searchItems.value = []; searched.value = false; searchError.value = ''; searching.value = false }
function reload() { clearSearch(); loadOverview(); loadRanking() }
async function refreshIndex() {
  refreshStarting.value = true
  overviewError.value = ''
  clearSearch()
  try {
    const data = await sendJson('/api/reason-vector/refresh', 'POST', {})
    if (disposed) return
    index.value = data.index
    await loadOverview()
  } catch (err) { if (!disposed) overviewError.value = err.message }
  finally { refreshStarting.value = false }
}
async function search() {
  if (!query.value.trim() || !canSearch.value || searching.value) return
  const id = ++searchRequest
  searching.value = true
  searchError.value = ''
  searchItems.value = []
  try {
    const data = await sendJson('/api/reason-vector/search', 'POST', { text: query.value, limit: limit.value ?? 20,
      minScore: useMinScore.value ? minScore.value : null })
    if (disposed || id !== searchRequest) return
    searchItems.value = data.items
    index.value = data.index
    searched.value = true
  } catch (err) { if (!disposed && id === searchRequest) searchError.value = err.message }
  finally { if (id === searchRequest) searching.value = false }
}
onMounted(reload)
onBeforeUnmount(() => { disposed = true; clearTimeout(pollTimer); rankingRequest++; overviewRequest++; searchRequest++ })
</script>

<style scoped>
.reason-vector-page { overflow-y: auto; display: block; }
.reason-vector-page > * { margin-bottom: 14px; }
h2 { margin: 0 auto 0 0; font-size: 20px; }
h3 { margin: 0 0 16px; font-size: 16px; }
.summary-grid { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 12px; }
.summary-grid > div { border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
.summary-grid span { display: block; color: var(--text-dim); font-size: 13px; }
.summary-grid strong { display: block; margin-top: 8px; font-size: 24px; }
.index-status { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; font-size: 13px; }
.hint-text { color: var(--text-dim); font-size: 13px; line-height: 1.7; }
.vector-panel { padding: 18px; border: 1px solid var(--border); border-radius: 8px; min-width: 0; }
.search-form .toolbar { margin-top: 12px; }
label { font-size: 13px; display: inline-flex; align-items: center; gap: 8px; }
.tag-filter { width: 240px; }
.sample-tag { margin-left: 8px; }
.el-pagination { margin-top: 16px; }
@media (max-width: 1000px) { .summary-grid { grid-template-columns: repeat(2, minmax(120px, 1fr)); } }
</style>
