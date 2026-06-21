<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
    variant?: 'primary' | 'accent' | 'ghost' | 'danger'
    size?: 'sm' | 'md' | 'lg'
    to?: string
    type?: 'button' | 'submit'
    disabled?: boolean
    block?: boolean
}>(), { variant: 'primary', size: 'md', type: 'button' })

const base = 'inline-flex items-center justify-center font-medium rounded-lg transition-colors ' +
    'disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none'

const variants: Record<string, string> = {
    primary: 'bg-ink text-white hover:bg-ink/90',
    accent: 'bg-accent-deep text-white hover:bg-accent',
    ghost: 'border border-surface-border text-ink hover:border-accent bg-white',
    danger: 'border border-red-300 text-red-600 hover:bg-red-50 bg-white',
}
const sizes: Record<string, string> = {
    sm: 'text-xs px-3 py-1.5',
    md: 'text-sm px-4 py-2',
    lg: 'text-base px-6 py-3',
}

const cls = computed(() => [
    base, variants[props.variant], sizes[props.size], props.block ? 'w-full' : '',
])
</script>

<template>
    <NuxtLink v-if="to" :to="to" :class="cls"><slot /></NuxtLink>
    <button v-else :type="type" :disabled="disabled" :class="cls"><slot /></button>
</template>
