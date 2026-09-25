<template>
  <div class="signal-details" v-loading="loading">
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-button v-if="error" size="small" @click="load">重试明细</el-button>
    <el-empty v-if="!loading && !error && !items.length" description="此标签当前没有有效关联信号" :image-size="50" />
    <article v-for="signal in items" :key="signal.id" class="signal-item">
      <header>
        <strong>{{ signal.name || signal.ts_code }}</strong>
        <span v-if="signal.name">{{ signal.ts_code }}</span>
        <span>{{ signal.trade_date }}</span>
        <el-tag :type="signal.mark_type === 'correct' ? 'success' : 'danger'" size="small">
          {{ signal.mark_type === 'correct' ? '好信号（correct）' : '差信号（fail）' }}
        </el-tag>
        <span>信号 ID：{{ signal.id }}</span>
      </header>
      <div class="evidence"><b>该标签原文依据</b><blockquote v-for="evidence in signal.evidence" :key="evidence">{{ evidence }}</blockquote></div>
      <details><summary>查看完整 reason</summary><p class="reason">{{ signal.reason }}</p></details>
    </article>
    <el-pagination v-if="total > 10" v-model:current-page="page" :page-size="10" :total="total"
      layout="total, prev, pager, next" small @current-change="load" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { getJson } from '../api.js'

const props = defineProps({ label: { type: String, required: true } })
const items = ref([])
const total = ref(0)
const page = ref(1)
const error = ref('')
const loading = ref(false)
let requestId = 0
async function load() {
  const id = ++requestId
  loading.value = true
  error.value = ''
  items.value = []
  try {
    const data = await getJson(`/api/reason-vector/signals?${new URLSearchParams({ label: props.label, page: page.value, pageSize: 10 })}`)
    if (id !== requestId) return
    items.value = data.items
    total.value = data.total
  } catch (err) {
    if (id === requestId) error.value = err.message
  } finally {
    if (id === requestId) loading.value = false
  }
}
watch(() => props.label, () => { page.value = 1; load() }, { immediate: true })
onBeforeUnmount(() => { requestId++ })
</script>

<style scoped>
.signal-details { padding: 12px 24px; }
.signal-item { padding: 14px 0; border-bottom: 1px solid var(--border); }
.signal-item header { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.evidence { margin-top: 12px; }
blockquote { margin: 8px 0; padding-left: 12px; border-left: 2px solid var(--accent); white-space: pre-wrap; overflow-wrap: anywhere; }
summary { color: var(--accent); cursor: pointer; margin-top: 10px; }
.reason { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; max-height: 420px; overflow: auto; }
.el-pagination { margin-top: 12px; }
</style>
