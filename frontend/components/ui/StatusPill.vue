<script setup lang="ts">
import { computed } from 'vue'
import { statusTone, statusLabel } from '~/utils/statusTone'

/**
 * The load-bearing status indicator — how transactional states become legible.
 * Tone mapping lives in utils/statusTone (single-sourced + unit-tested).
 */
const props = defineProps<{ status?: string | null; label?: string }>()

const cls = computed(() => statusTone(props.status))
const text = computed(() => props.label ?? statusLabel(props.status))
</script>

<template>
    <span
        class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium capitalize"
        :class="cls">
        <slot name="dot" />
        {{ text }}
    </span>
</template>
