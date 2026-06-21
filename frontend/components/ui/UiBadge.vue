<script setup lang="ts">
import { computed } from 'vue'
const props = withDefaults(defineProps<{ tone?: 'neutral' | 'accent' | 'ink' }>(), { tone: 'neutral' })
const tones: Record<string, string> = {
    neutral: 'bg-slate-100 text-slate-600',
    accent: 'bg-accent/15 text-accent-deep',
    ink: 'bg-ink/10 text-ink',
}
const cls = computed(() => tones[props.tone])
</script>

<template>
    <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium" :class="cls">
        <slot />
    </span>
</template>
