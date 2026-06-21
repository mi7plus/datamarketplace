<script setup lang="ts">
import { computed } from 'vue'

/**
 * The load-bearing status indicator — how transactional states become legible.
 * Accent for active/settlement, muted/ink for neutral structure, a clear but
 * non-alarming amber for disputes. AA-safe (dark text on light tints).
 */
const props = defineProps<{ status?: string | null; label?: string }>()

const MAP: Record<string, string> = {
    // request states
    draft: 'bg-slate-100 text-slate-600',
    open: 'bg-ink/10 text-ink',
    partially_fulfilled: 'bg-accent/15 text-accent-deep',
    completed: 'bg-accent/20 text-accent-deep',
    fulfilled: 'bg-accent/20 text-accent-deep',
    review: 'bg-slate-100 text-slate-700',
    expired: 'bg-slate-200 text-slate-600',
    // submission states
    pending: 'bg-slate-100 text-slate-600',
    validated: 'bg-ink/10 text-ink',
    accepted: 'bg-accent/15 text-accent-deep',
    partially_accepted: 'bg-accent/15 text-accent-deep',
    paid: 'bg-accent/20 text-accent-deep',
    rejected: 'bg-slate-200 text-slate-600',
    rejected_invalid: 'bg-slate-200 text-slate-600',
    disputed: 'bg-amber-100 text-amber-800',
    // escrow / catalog
    held: 'bg-ink/10 text-ink',
    released: 'bg-accent/20 text-accent-deep',
    refunded: 'bg-slate-100 text-slate-600',
    sold_out: 'bg-slate-200 text-slate-600',
    taken_down: 'bg-amber-100 text-amber-800',
    quarantined: 'bg-amber-100 text-amber-800',
    catalog: 'bg-accent/15 text-accent-deep',
    collect: 'bg-accent/15 text-accent-deep',
    request: 'bg-ink/10 text-ink',
}

const key = computed(() => (props.status ?? '').toLowerCase())
const cls = computed(() => MAP[key.value] ?? 'bg-slate-100 text-slate-600')
const text = computed(() => props.label ?? (props.status ?? '').replace(/_/g, ' '))
</script>

<template>
    <span
        class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium capitalize"
        :class="cls">
        <slot name="dot" />
        {{ text }}
    </span>
</template>
