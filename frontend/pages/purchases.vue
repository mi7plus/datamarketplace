<script setup lang="ts">
import { ref, onMounted } from 'vue'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import { useApi } from '~/composables/useApi'

const api = useApi()
const purchases = ref<any[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
    try {
        purchases.value = await api.get('/purchases/')
    } catch (e: any) {
        error.value = e.message
    } finally {
        loading.value = false
    }
})

async function download(id: string) {
    const res = await api.get(`/purchases/${id}/download`)
    if (res?.url) window.open(res.url, '_blank')
}
</script>

<template>
    <PageWrapper>
        <h1 class="text-2xl font-bold text-ink mb-6">My Purchases</h1>
        <div v-if="loading" class="text-surface-label text-sm py-8 text-center">Loading…</div>
        <div v-else-if="error" class="text-red-500 text-sm py-8 text-center">{{ error }}</div>
        <div v-else-if="purchases.length === 0" class="text-surface-label text-sm py-8 text-center">
            No purchases yet. <NuxtLink to="/catalog" class="text-accent-deep hover:underline">Browse the catalog</NuxtLink>.
        </div>
        <div v-else class="space-y-3">
            <div v-for="p in purchases" :key="p.id"
                class="border border-surface-border rounded-lg p-4 bg-white flex items-center justify-between gap-4">
                <div class="text-sm">
                    <div class="font-medium text-ink">{{ p.quantity?.toLocaleString() }} records · ${{ p.amount }}</div>
                    <div class="text-xs text-surface-label">
                        {{ p.created_at ? new Date(p.created_at).toLocaleString() : '' }} · {{ p.status }}
                    </div>
                </div>
                <button v-if="p.status === 'paid'" @click="download(p.id)"
                    class="bg-ink text-white px-4 py-2 rounded-lg text-sm hover:bg-ink/90">
                    Download
                </button>
            </div>
        </div>
    </PageWrapper>
</template>
