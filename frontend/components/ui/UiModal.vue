<script setup lang="ts">
import { watch } from 'vue'

const props = defineProps<{ open: boolean; title?: string }>()
const emit = defineEmits<{ close: [] }>()

// Close on Escape; lock scroll while open.
function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') emit('close')
}
watch(() => props.open, (v) => {
    if (typeof document === 'undefined') return
    document.body.style.overflow = v ? 'hidden' : ''
    if (v) window.addEventListener('keydown', onKey)
    else window.removeEventListener('keydown', onKey)
})
</script>

<template>
    <Teleport to="body">
        <div v-if="open" class="fixed inset-0 z-[100] flex items-center justify-center p-4"
            role="dialog" aria-modal="true">
            <div class="absolute inset-0 bg-ink/40" @click="emit('close')" />
            <div class="relative bg-white rounded-xl border border-surface-border shadow-xl
                        max-w-lg w-full p-6 z-10">
                <div v-if="title" class="flex items-center justify-between mb-4">
                    <h2 class="font-wordmark text-xl text-ink">{{ title }}</h2>
                    <button class="text-muted hover:text-ink" aria-label="Close" @click="emit('close')">✕</button>
                </div>
                <slot />
            </div>
        </div>
    </Teleport>
</template>
