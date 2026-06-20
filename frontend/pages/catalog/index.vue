<script setup lang="ts">
import { ref, onMounted } from 'vue'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import { useApi } from '~/composables/useApi'

const api = useApi()
const listings = ref<any[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
    try {
        listings.value = await api.get('/listings/')
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
            <h1 class="text-2xl font-bold text-ink">Catalog</h1>
            <NuxtLink to="/catalog/list"
                class="text-sm bg-ink text-white px-4 py-2 rounded-lg hover:bg-ink/90 transition-colors">
                + List a dataset
            </NuxtLink>
        </div>
        <p class="text-muted text-sm mb-6">Buy existing datasets — pay per record, settled in escrow.</p>

        <div v-if="loading" class="text-surface-label text-sm py-8 text-center">Loading catalog…</div>
        <div v-else-if="error" class="text-red-500 text-sm py-8 text-center">{{ error }}</div>
        <div v-else-if="listings.length === 0" class="text-surface-label text-sm py-8 text-center">
            No datasets listed yet.
        </div>

        <div v-else class="grid gap-4 md:grid-cols-2">
            <NuxtLink v-for="l in listings" :key="l.id" :to="`/catalog/${l.id}`"
                class="block border border-surface-border rounded-lg p-4 bg-white hover:border-accent transition-colors">
                <div class="flex justify-between items-start gap-3">
                    <div class="min-w-0">
                        <h3 class="font-semibold text-ink truncate">{{ l.title }}</h3>
                        <p v-if="l.description" class="text-muted text-sm mt-1 line-clamp-2">{{ l.description }}</p>
                    </div>
                    <div class="text-right shrink-0">
                        <div class="font-bold text-lg text-ink">${{ l.price_per_unit }}</div>
                        <div class="text-xs text-surface-label">/ {{ l.unit ?? 'record' }}</div>
                    </div>
                </div>
                <div class="flex flex-wrap items-center gap-2 mt-3 text-xs">
                    <span class="px-2 py-0.5 rounded-full bg-accent/15 text-accent-deep">
                        {{ l.available_quantity?.toLocaleString() }} available
                    </span>
                    <span v-if="l.quality_score != null" class="text-muted">
                        Quality {{ Math.round(l.quality_score * 100) }}%
                    </span>
                    <span v-if="l.license_name" class="text-muted">· {{ l.license_name }}</span>
                    <span v-if="l.provenance" class="text-surface-label truncate">· {{ l.provenance }}</span>
                </div>
            </NuxtLink>
        </div>
    </PageWrapper>
</template>
