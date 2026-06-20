<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import BackButton from '~/components/BackButton.vue'
import { useApi } from '~/composables/useApi'

const api = useApi()
const router = useRouter()

const title = ref('')
const description = ref('')
const unit = ref('row')
const pricePerUnit = ref(1.0)
const provenance = ref('')
const file = ref<File | null>(null)
const warrantyRights = ref(false)
const warrantyPrivacy = ref(false)
const submitting = ref(false)
const error = ref<string | null>(null)

const fileError = computed(() => {
    if (!file.value) return null
    const ext = file.value.name.split('.').pop()?.toLowerCase()
    if (!['csv', 'jsonl'].includes(ext ?? '')) return 'Only CSV and JSONL files are accepted'
    if (file.value.size > 100 * 1024 * 1024) return 'File must be under 100 MB'
    return null
})
const ok = computed(() =>
    file.value && !fileError.value && title.value && pricePerUnit.value > 0 &&
    warrantyRights.value && warrantyPrivacy.value
)

function onFile(e: Event) {
    file.value = (e.target as HTMLInputElement).files?.[0] ?? null
}

async function submit() {
    if (!ok.value || !file.value) return
    submitting.value = true
    error.value = null
    try {
        const fd = new FormData()
        fd.append('title', title.value)
        fd.append('description', description.value)
        fd.append('unit', unit.value)
        fd.append('price_per_unit', String(pricePerUnit.value))
        fd.append('provenance', provenance.value)
        fd.append('warranted', 'true')
        fd.append('file', file.value)
        const res = await api.postForm('/listings/', fd)
        router.push(`/catalog/${res.id}`)
    } catch (e: any) {
        error.value = e.message
    } finally {
        submitting.value = false
    }
}
</script>

<template>
    <PageWrapper class="max-w-2xl">
        <BackButton fallback="/catalog" />
        <h1 class="text-2xl font-bold text-ink mb-6">List a dataset</h1>

        <div class="space-y-4">
            <label class="block text-sm">
                <span class="block text-muted mb-1">Title *</span>
                <input v-model="title" class="w-full border border-surface-border rounded px-3 py-2" />
            </label>
            <label class="block text-sm">
                <span class="block text-muted mb-1">Description</span>
                <textarea v-model="description" rows="2" class="w-full border border-surface-border rounded px-3 py-2" />
            </label>
            <div class="flex gap-4 flex-wrap">
                <label class="block text-sm">
                    <span class="block text-muted mb-1">Price per record ($) *</span>
                    <input v-model.number="pricePerUnit" type="number" min="0.01" step="0.01"
                        class="w-40 border border-surface-border rounded px-3 py-2" />
                </label>
                <label class="block text-sm">
                    <span class="block text-muted mb-1">Unit</span>
                    <input v-model="unit" class="w-32 border border-surface-border rounded px-3 py-2" />
                </label>
            </div>
            <label class="block text-sm">
                <span class="block text-muted mb-1">Provenance — where the data came from</span>
                <input v-model="provenance" placeholder="e.g. first-party CRM export, 2026"
                    class="w-full border border-surface-border rounded px-3 py-2" />
            </label>
            <label class="block text-sm">
                <span class="block text-muted mb-1">Dataset file (CSV or JSONL) *</span>
                <input type="file" accept=".csv,.jsonl" @change="onFile" class="block w-full text-sm" />
                <span v-if="fileError" class="text-red-500 text-xs">{{ fileError }}</span>
            </label>

            <div class="border border-amber-200 rounded-lg p-4 bg-amber-50 space-y-2 text-sm">
                <label class="flex items-start gap-2">
                    <input type="checkbox" v-model="warrantyRights" class="mt-0.5" />
                    <span class="text-gray-700">I have the legal right to sell or share this dataset.</span>
                </label>
                <label class="flex items-start gap-2">
                    <input type="checkbox" v-model="warrantyPrivacy" class="mt-0.5" />
                    <span class="text-gray-700">No unconsented personal data; any personal data is anonymised per GDPR.</span>
                </label>
            </div>

            <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
            <button @click="submit" :disabled="!ok || submitting"
                class="bg-ink text-white px-5 py-2 rounded-lg text-sm hover:bg-ink/90 disabled:opacity-50">
                {{ submitting ? 'Validating & listing…' : 'List dataset' }}
            </button>
        </div>
    </PageWrapper>
</template>
