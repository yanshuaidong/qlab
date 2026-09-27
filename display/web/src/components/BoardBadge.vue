<script setup>
import { computed } from 'vue'
import { boardOf } from '../utils/board.js'

const props = defineProps({
  code: { type: String, default: '' },
})

const board = computed(() => boardOf(props.code))
</script>

<template>
  <span
    v-if="board"
    class="board-badge"
    :class="`is-${board.key}`"
    :title="board.title"
  >{{ board.char }}</span>
</template>
