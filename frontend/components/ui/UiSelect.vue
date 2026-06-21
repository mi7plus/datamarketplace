<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
    modelValue?: string
    label?: string
    options: { value: string; label: string }[]
    error?: string | null
    hint?: string
    required?: boolean
    id?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [v: string] }>()
const fieldId = computed(() => props.id ?? `s-${Math.random().toString(36).slice(2, 8)}`)
</script>

<template>
    <div class="space-y-1">
        <label v-if="label" :for="fieldId" class="block text-sm text-muted">
            {{ label }} <span v-if="required" class="text-red-500" aria-hidden="true">*</span>
        </label>
        <select
            :id="fieldId"
            :value="modelValue"
            :required="required"
            :aria-invalid="!!error"
            class="w-full rounded-lg border px-3 py-2 text-sm text-ink bg-white transition-colors
                   focus-visible:outline-none focus-visible:border-accent-deep"
            :class="error ? 'border-red-400' : 'border-surface-border'"
            @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
        >
            <option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <p v-if="error" class="text-xs text-red-600">{{ error }}</p>
        <p v-else-if="hint" class="text-xs text-surface-label">{{ hint }}</p>
    </div>
</template>
