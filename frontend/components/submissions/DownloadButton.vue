<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '~/stores/auth'
import { useRuntimeConfig } from '#app'

const props = defineProps<{ submissionId: string }>()

const auth = useAuthStore()
const config = useRuntimeConfig()

const loading = ref(false)
const error = ref<string | null>(null)

async function download() {
    loading.value = true
    error.value = null
    try {
        const res = await fetch(
            `${config.public.apiBase}/submissions/${props.submissionId}/download`,
            { headers: { Authorization: `Bearer ${auth.token}` } }
        )
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || 'Download failed')

        // Open the pre-signed URL in a new tab
        window.open(data.url, '_blank', 'noopener')
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
            @click="download"
            :disabled="loading"
            class="px-3 py-1 rounded bg-emerald-600 text-white text-xs
                   hover:bg-emerald-700 disabled:opacity-50">
            {{ loading ? 'Generating link…' : 'Download dataset' }}
        </button>
        <p v-if="error" class="text-red-500 text-xs mt-1">{{ error }}</p>
    </div>
</template>
