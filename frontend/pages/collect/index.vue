<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import { useApi } from '~/composables/useApi'

const api = useApi()
const requests = ref<any[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const collectRequests = computed(() =>
    requests.value.filter(r => r.mode === 'collect' && ['open', 'partially_fulfilled'].includes(r.status))
)

onMounted(async () => {
    try {
        requests.value = await api.get('/requests/')
    } catch (e: any) {
        error.value = e.message
    } finally {
        loading.value = false
    }
})
</script>

<template>
    <PageWrapper>
        <div class="flex items-center justify-between mb-2">
            <h1 class="text-2xl font-bold text-ink">Collect</h1>
            <NuxtLink to="/requests/create"
                class="text-sm bg-ink text-white px-4 py-2 rounded-lg hover:bg-ink/90 transition-colors">
                + Commission a collection
            </NuxtLink>
        </div>
        <p class="text-muted text-sm mb-6">
            Commission fresh data gathered in the field. BYO-workforce orgs accept a funded
            collection, their agents submit structured entries (geo + photo + consent), and
            valid records settle per record through escrow.
        </p>

        <div v-if="loading" class="text-surface-label text-sm py-8 text-center">Loading…</div>
        <div v-else-if="error" class="text-red-500 text-sm py-8 text-center">{{ error }}</div>
        <div v-else-if="collectRequests.length === 0" class="text-surface-label text-sm py-8 text-center">
            No open collection requests right now.
        </div>

        <div v-else class="grid gap-4">
            <NuxtLink v-for="r in collectRequests" :key="r.id" :to="`/collect/${r.id}`"
                class="block border border-surface-border rounded-lg p-4 bg-white hover:border-accent transition-colors">
                <div class="flex justify-between items-start gap-3">
                    <div class="min-w-0">
                        <h3 class="font-semibold text-ink truncate">{{ r.title }}</h3>
                        <p v-if="r.description" class="text-muted text-sm mt-1 line-clamp-2">{{ r.description }}</p>
                    </div>
                    <div class="text-right shrink-0">
                        <div class="font-bold text-lg text-ink">${{ r.price_per_unit }}</div>
                        <div class="text-xs text-surface-label">/ {{ r.unit ?? 'record' }}</div>
                    </div>
                </div>
                <div class="flex flex-wrap items-center gap-2 mt-3 text-xs">
                    <span class="px-2 py-0.5 rounded-full bg-accent/15 text-accent-deep">
                        {{ ((r.amount_required ?? 0) - (r.accepted_total ?? 0)).toLocaleString() }} {{ r.unit ?? 'records' }} still needed
                    </span>
                    <span v-if="r.collection_spec?.geo_required" class="text-muted">· geo</span>
                    <span v-if="r.collection_spec?.photo_required" class="text-muted">· photo</span>
                    <span v-if="r.collection_spec?.consent_required" class="text-muted">· consent</span>
                </div>
            </NuxtLink>
        </div>
    </PageWrapper>
</template>
