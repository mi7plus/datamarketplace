<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '~/stores/auth'
import { useRuntimeConfig } from '#app'

const props = defineProps<{ submissionId: string }>()
const emit = defineEmits<{ disputed: [] }>()

const auth = useAuthStore()
const config = useRuntimeConfig()

const open = ref(false)
const reason = ref('')
const loading = ref(false)
const error = ref<string | null>(null)

async function submit() {
    if (!reason.value.trim()) return
    loading.value = true
    error.value = null
    try {
        const res = await fetch(
            `${config.public.apiBase}/disputes/${props.submissionId}/open`,
            {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${auth.token}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ reason: reason.value }),
            }
        )
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || 'Failed to open dispute')
        open.value = false
        emit('disputed')
    } catch (e: any) {
        error.value = e.message
    } finally {
        loading.value = false
    }
}
</script>

<template>
    <div>
        <button
            v-if="!open"
            @click="open = true"
            class="text-xs text-orange-600 border border-orange-300 px-3 py-1 rounded hover:bg-orange-50">
            Dispute
        </button>

        <div v-else class="mt-2 space-y-2 border border-orange-200 rounded p-3 bg-orange-50">
            <p class="text-xs font-medium text-orange-700">Describe the issue with this submission:</p>
            <textarea
                v-model="reason"
                rows="3"
                placeholder="e.g. Data does not match the spec — columns missing, wrong types…"
                class="w-full text-xs border rounded px-2 py-1 resize-none" />
            <p v-if="error" class="text-red-500 text-xs">{{ error }}</p>
            <div class="flex gap-2">
                <button
                    @click="submit"
                    :disabled="loading || !reason.trim()"
                    class="text-xs px-3 py-1 rounded bg-orange-600 text-white hover:bg-orange-700 disabled:opacity-50">
                    {{ loading ? 'Submitting…' : 'Open dispute' }}
                </button>
                <button @click="open = false" class="text-xs text-gray-500 hover:underline">Cancel</button>
            </div>
        </div>
    </div>
</template>
