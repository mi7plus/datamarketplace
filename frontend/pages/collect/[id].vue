<script setup lang="ts">
// Collecting data requires an account — redirect to /login if signed out.
definePageMeta({ middleware: 'auth' })
import { ref, reactive, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import BackButton from '~/components/BackButton.vue'
import { useApi } from '~/composables/useApi'

const route = useRoute()
const api = useApi()

const request = ref<any>(null)
const dispatch = ref<any>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const entryError = ref<string | null>(null)
const lastEntry = ref<any>(null)
const finalizeResult = ref<any>(null)

const spec = computed(() => request.value?.collection_spec ?? {})
const form = reactive<Record<string, any>>({})
const geoLat = ref<number | null>(null)
const geoLng = ref<number | null>(null)
const photoRef = ref('')
const consentBasis = ref('')
const contributor = ref('')

onMounted(async () => {
    try {
        request.value = await api.get(`/requests/${route.params.id}`)
    } catch (e: any) {
        error.value = e.message
    } finally {
        loading.value = false
    }
})

async function accept() {
    try {
        dispatch.value = await api.post('/collect/dispatches', { request_id: request.value.id })
    } catch (e: any) {
        error.value = e.message
    }
}

async function refreshDispatch() {
    dispatch.value = await api.get(`/collect/dispatches/${dispatch.value.id}`)
}

async function submitEntry() {
    entryError.value = null
    lastEntry.value = null
    try {
        const res = await api.post(`/collect/dispatches/${dispatch.value.id}/entries`, {
            data: { ...form },
            contributor_ref: contributor.value || null,
            geo_lat: geoLat.value, geo_lng: geoLng.value,
            photo_ref: photoRef.value || null,
            consent_basis: consentBasis.value || null,
            lawful_basis: consentBasis.value ? 'consent' : null,
        })
        lastEntry.value = res
        if (res.status === 'valid') {
            for (const k of Object.keys(form)) form[k] = ''
            photoRef.value = ''
        }
        await refreshDispatch()
    } catch (e: any) {
        entryError.value = e.message
    }
}

async function finalize() {
    try {
        finalizeResult.value = await api.post(`/collect/dispatches/${dispatch.value.id}/finalize`, {})
        await refreshDispatch()
    } catch (e: any) {
        error.value = e.message
    }
}
</script>

<template>
    <PageWrapper class="max-w-2xl">
        <BackButton fallback="/collect" />
        <div v-if="loading" class="text-surface-label text-sm py-12 text-center">Loading…</div>
        <div v-else-if="error" class="text-red-500 text-sm py-12 text-center">{{ error }}</div>

        <div v-else-if="request" class="space-y-6">
            <div>
                <h1 class="text-2xl font-bold text-ink">{{ request.title }}</h1>
                <p v-if="request.description" class="text-muted mt-2">{{ request.description }}</p>
                <p class="text-sm text-muted mt-2">
                    ${{ request.price_per_unit }} / {{ request.unit }} ·
                    {{ ((request.amount_required ?? 0) - (request.accepted_total ?? 0)).toLocaleString() }} still needed
                </p>
            </div>

            <button v-if="!dispatch" @click="accept"
                class="bg-accent-deep text-white px-5 py-2 rounded-lg text-sm hover:bg-accent">
                Accept this collection
            </button>

            <template v-else>
                <div class="border border-surface-border rounded-lg p-4 bg-white text-sm flex gap-6">
                    <span><strong>{{ dispatch.entries_valid }}</strong> valid</span>
                    <span class="text-muted">{{ dispatch.entries_total }} submitted</span>
                    <span class="text-surface-label">status: {{ dispatch.status }}</span>
                </div>

                <!-- Entry form (dynamic from collection_spec) -->
                <div v-if="dispatch.status === 'open'" class="border border-accent rounded-lg p-4 bg-white space-y-3">
                    <h2 class="font-semibold text-sm text-ink uppercase tracking-wide">Submit a field entry</h2>
                    <label v-for="f in spec.fields" :key="f.name" class="block text-sm">
                        <span class="block text-muted mb-1">{{ f.name }} <span v-if="f.required" class="text-red-500">*</span>
                            <span class="text-surface-label">({{ f.type }})</span></span>
                        <input v-model="form[f.name]" class="w-full border border-surface-border rounded px-3 py-2" />
                    </label>

                    <div v-if="spec.geo_required" class="flex gap-3">
                        <label class="text-sm flex-1"><span class="block text-muted mb-1">Latitude *</span>
                            <input v-model.number="geoLat" type="number" step="any" class="w-full border border-surface-border rounded px-3 py-2" /></label>
                        <label class="text-sm flex-1"><span class="block text-muted mb-1">Longitude *</span>
                            <input v-model.number="geoLng" type="number" step="any" class="w-full border border-surface-border rounded px-3 py-2" /></label>
                    </div>
                    <label v-if="spec.photo_required" class="block text-sm">
                        <span class="block text-muted mb-1">Photo reference *</span>
                        <input v-model="photoRef" class="w-full border border-surface-border rounded px-3 py-2" /></label>
                    <label v-if="spec.consent_required" class="block text-sm">
                        <span class="block text-muted mb-1">Consent basis *</span>
                        <input v-model="consentBasis" placeholder="e.g. subject opt-in" class="w-full border border-surface-border rounded px-3 py-2" /></label>
                    <label class="block text-sm">
                        <span class="block text-muted mb-1">Agent / contributor</span>
                        <input v-model="contributor" class="w-full border border-surface-border rounded px-3 py-2" /></label>

                    <button @click="submitEntry"
                        class="bg-ink text-white px-4 py-2 rounded-lg text-sm hover:bg-ink/90">Submit entry</button>
                    <p v-if="entryError" class="text-red-600 text-sm">{{ entryError }}</p>
                    <p v-if="lastEntry?.status === 'valid'" class="text-accent-deep text-sm">✓ Entry accepted</p>
                    <p v-else-if="lastEntry?.status === 'rejected'" class="text-red-600 text-sm">
                        ✗ Rejected: {{ lastEntry.validation_errors.join('; ') }}
                    </p>

                    <div class="pt-2 border-t">
                        <button @click="finalize" :disabled="dispatch.entries_valid < 1"
                            class="bg-accent-deep text-white px-4 py-2 rounded-lg text-sm hover:bg-accent disabled:opacity-50">
                            Finalize &amp; submit {{ dispatch.entries_valid }} records
                        </button>
                    </div>
                </div>

                <div v-if="finalizeResult" class="border border-accent rounded-lg p-4 bg-white text-sm text-accent-deep">
                    ● Finalized — {{ finalizeResult.validated_amount }} records submitted for review
                    ({{ finalizeResult.deduplicated }} duplicates removed). The buyer reviews and accepts.
                </div>
            </template>
        </div>
    </PageWrapper>
</template>
