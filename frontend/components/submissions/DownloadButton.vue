<script setup lang="ts">
import { ref } from 'vue'
import { useApi } from '~/composables/useApi'

const props = defineProps<{ submissionId: string }>()
const api = useApi()

const loading = ref(false)
const error = ref<string | null>(null)
const manifest = ref<any>(null)

async function download() {
    loading.value = true
    error.value = null
    try {
        const data = await api.get(`/submissions/${props.submissionId}/download`)
        manifest.value = data.manifest ?? null
        if (data.streamed) {
            // Envelope-encrypted dataset (E5): the server decrypts and streams the
            // bytes over an authenticated request — fetch as a blob and save it.
            const blob = await api.getBlob(data.download_path)
            const objectUrl = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = objectUrl
            a.download = data.filename || 'dataset'
            a.click()
            URL.revokeObjectURL(objectUrl)
        } else {
            window.open(data.url, '_blank', 'noopener')
        }
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
            class="px-3 py-1 rounded bg-accent-deep text-white text-xs
                   hover:bg-accent disabled:opacity-50">
            {{ loading ? 'Generating link…' : 'Download dataset' }}
        </button>
        <p v-if="error" class="text-red-500 text-xs mt-1">{{ error }}</p>

        <!-- Compliance manifest travels with the delivery (Phase 8) -->
        <div v-if="manifest" class="mt-2 text-xs text-muted border border-surface-border rounded p-2 space-y-0.5">
            <div><span class="text-surface-label">Source:</span> {{ manifest.source }}</div>
            <div v-if="manifest.license">
                <span class="text-surface-label">License:</span> {{ manifest.license.name }}
            </div>
            <div v-if="manifest.consent">
                <span class="text-surface-label">Consent:</span>
                {{ manifest.consent.with_consent_basis }}/{{ manifest.record_count }} with basis
            </div>
            <div v-if="manifest.provenance" class="truncate">
                <span class="text-surface-label">Provenance:</span> {{ manifest.provenance }}
            </div>
        </div>
    </div>
</template>
