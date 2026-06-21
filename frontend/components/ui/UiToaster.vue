<script setup lang="ts">
import { useToast } from '~/composables/useToast'
const { toasts, dismiss } = useToast()

const tones: Record<string, string> = {
    success: 'border-accent-deep',
    error: 'border-red-400',
    info: 'border-surface-border',
}
</script>

<template>
    <div class="fixed bottom-4 right-4 z-[200] space-y-2 w-80 max-w-[90vw]" aria-live="polite">
        <div v-for="t in toasts" :key="t.id"
            class="bg-white border-l-4 border border-surface-border rounded-lg shadow px-4 py-3 text-sm
                   flex items-start justify-between gap-3"
            :class="tones[t.tone]">
            <span class="text-ink">{{ t.message }}</span>
            <button class="text-muted hover:text-ink shrink-0" aria-label="Dismiss"
                @click="dismiss(t.id)">✕</button>
        </div>
    </div>
</template>
