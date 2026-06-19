<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '~/stores/auth'
import { useRuntimeConfig } from '#app'

const props = defineProps<{ submissionId: string }>()
const emit = defineEmits<{ reviewed: [] }>()

const auth = useAuthStore()
const config = useRuntimeConfig()

const rating = ref(5)
const comment = ref('')
const loading = ref(false)
const error = ref<string | null>(null)
const done = ref(false)

async function submit() {
    loading.value = true
    error.value = null
    try {
        const res = await fetch(`${config.public.apiBase}/reviews/`, {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${auth.token}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ submission_id: props.submissionId, rating: rating.value, comment: comment.value || null }),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || 'Review failed')
        done.value = true
        emit('reviewed')
    } catch (e: any) {
        error.value = e.message
    } finally {
        loading.value = false
    }
}
</script>

<template>
    <div v-if="!done" class="mt-2 border border-gray-200 rounded p-3 space-y-2 bg-gray-50">
        <p class="text-xs font-medium text-gray-700">Leave a review</p>
        <div class="flex gap-1">
            <button
                v-for="n in 5" :key="n"
                @click="rating = n"
                class="text-lg"
                :class="n <= rating ? 'text-yellow-400' : 'text-gray-300'">
                ★
            </button>
        </div>
        <textarea
            v-model="comment"
            rows="2"
            placeholder="Optional comment…"
            class="w-full text-xs border rounded px-2 py-1 resize-none" />
        <p v-if="error" class="text-red-500 text-xs">{{ error }}</p>
        <button
            @click="submit"
            :disabled="loading"
            class="text-xs px-3 py-1 rounded bg-gray-700 text-white hover:bg-gray-900 disabled:opacity-50">
            {{ loading ? 'Saving…' : 'Submit review' }}
        </button>
    </div>
    <p v-else class="text-xs text-green-600 mt-1">Review submitted — thank you.</p>
</template>
