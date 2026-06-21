<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
    modelValue?: string | number
    label?: string
    type?: string
    placeholder?: string
    error?: string | null
    hint?: string
    required?: boolean
    id?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [v: string] }>()

const fieldId = computed(() => props.id ?? `f-${Math.random().toString(36).slice(2, 8)}`)
const inputClass = computed(() => [
    'w-full rounded-lg border px-3 py-2 text-sm text-ink bg-white transition-colors',
    'focus-visible:outline-none focus-visible:border-accent-deep',
    props.error ? 'border-red-400' : 'border-surface-border',
])
</script>

<template>
    <div class="space-y-1">
        <label v-if="label" :for="fieldId" class="block text-sm text-muted">
            {{ label }} <span v-if="required" class="text-red-500" aria-hidden="true">*</span>
        </label>
        <input
            :id="fieldId"
            :type="type ?? 'text'"
            :value="modelValue"
            :placeholder="placeholder"
            :required="required"
            :aria-invalid="!!error"
            :aria-describedby="error ? `${fieldId}-err` : undefined"
            :class="inputClass"
            @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
        />
        <p v-if="error" :id="`${fieldId}-err`" class="text-xs text-red-600">{{ error }}</p>
        <p v-else-if="hint" class="text-xs text-surface-label">{{ hint }}</p>
    </div>
</template>
