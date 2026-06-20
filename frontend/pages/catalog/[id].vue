<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import BackButton from '~/components/BackButton.vue'
import { useApi } from '~/composables/useApi'
import { useAuthStore } from '~/stores/auth'

const route = useRoute()
const api = useApi()
const auth = useAuthStore()

const listing = ref<any>(null)
const sample = ref<any[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const quantity = ref(1)
const buying = ref(false)
const purchase = ref<any>(null)
const buyError = ref<string | null>(null)

const total = computed(() =>
    listing.value ? (quantity.value * listing.value.price_per_unit).toFixed(2) : '0.00'
)

onMounted(async () => {
    try {
        const id = route.params.id as string
        listing.value = await api.get(`/listings/${id}`)
        const s = await api.get(`/listings/${id}/sample`)
        sample.value = s.sample ?? []
        quantity.value = Math.min(1, listing.value.available_quantity)
    } catch (e: any) {
        error.value = e.message
    } finally {
        loading.value = false
    }
})

async function buy() {
    buying.value = true
    buyError.value = null
    try {
        const res = await api.post(`/listings/${listing.value.id}/purchase`, { quantity: quantity.value })
        purchase.value = res.purchase
        listing.value.available_quantity = res.remaining_in_listing
    } catch (e: any) {
        buyError.value = e.message
    } finally {
        buying.value = false
    }
}

async function download() {
    const res = await api.get(`/purchases/${purchase.value.id}/download`)
    if (res?.url) window.open(res.url, '_blank')
}
</script>

<template>
    <PageWrapper>
        <BackButton fallback="/catalog" />
        <div v-if="loading" class="text-surface-label text-sm py-12 text-center">Loading…</div>
        <div v-else-if="error" class="text-red-500 text-sm py-12 text-center">{{ error }}</div>

        <div v-else-if="listing" class="space-y-6 max-w-3xl">
            <div class="flex items-start justify-between gap-4">
                <div>
                    <h1 class="text-2xl font-bold text-ink">{{ listing.title }}</h1>
                    <p v-if="listing.description" class="text-muted mt-2">{{ listing.description }}</p>
                </div>
                <div class="text-right shrink-0">
                    <div class="font-bold text-xl text-ink">${{ listing.price_per_unit }}</div>
                    <div class="text-xs text-surface-label">/ {{ listing.unit ?? 'record' }}</div>
                </div>
            </div>

            <!-- Provenance / license / quality -->
            <div class="border border-surface-border rounded-lg p-4 bg-white">
                <dl class="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
                    <dt class="text-muted">Available</dt>
                    <dd class="font-medium">{{ listing.available_quantity?.toLocaleString() }} {{ listing.unit }}</dd>
                    <dt class="text-muted">Quality</dt>
                    <dd>{{ listing.quality_score != null ? Math.round(listing.quality_score * 100) + '%' : '—' }}</dd>
                    <template v-if="listing.license_name">
                        <dt class="text-muted">License</dt><dd>{{ listing.license_name }}</dd>
                    </template>
                    <template v-if="listing.provenance">
                        <dt class="text-muted">Provenance</dt><dd>{{ listing.provenance }}</dd>
                    </template>
                </dl>
            </div>

            <!-- Sample preview -->
            <div v-if="sample.length" class="border border-surface-border rounded-lg p-4 bg-white">
                <h2 class="font-semibold text-sm text-ink uppercase tracking-wide mb-3">Sample preview</h2>
                <div class="overflow-x-auto">
                    <table class="text-xs border-collapse w-full">
                        <thead>
                            <tr class="bg-surface">
                                <th v-for="k in Object.keys(sample[0])" :key="k"
                                    class="border border-surface-border px-2 py-1 text-left font-mono font-normal text-muted">
                                    {{ k }}
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="(row, i) in sample" :key="i">
                                <td v-for="(val, key) in row" :key="key"
                                    class="border border-surface-border px-2 py-1 font-mono">{{ val }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Purchase -->
            <div v-if="!purchase" class="border border-accent rounded-lg p-4 bg-white space-y-3">
                <h2 class="font-semibold text-sm text-ink uppercase tracking-wide">Buy records</h2>
                <div class="flex items-end gap-4 flex-wrap">
                    <label class="text-sm">
                        <span class="block text-muted mb-1">Quantity</span>
                        <input v-model.number="quantity" type="number" min="1" :max="listing.available_quantity"
                            class="w-32 border border-surface-border rounded px-3 py-2 text-sm" />
                    </label>
                    <div class="text-sm">
                        <span class="block text-muted mb-1">Total</span>
                        <span class="font-bold text-lg text-ink">${{ total }}</span>
                    </div>
                    <button @click="buy" :disabled="buying || quantity < 1 || quantity > listing.available_quantity"
                        class="bg-accent-deep text-white px-5 py-2 rounded-lg text-sm hover:bg-accent disabled:opacity-50">
                        {{ buying ? 'Settling…' : 'Buy & settle in escrow' }}
                    </button>
                </div>
                <p v-if="buyError" class="text-red-600 text-sm">{{ buyError }}</p>
                <p class="text-xs text-surface-label">
                    You pay per record; funds settle to the supplier through escrow. You receive exactly the
                    quantity you buy.
                </p>
            </div>

            <!-- Settled -->
            <div v-else class="border border-accent rounded-lg p-4 bg-white space-y-2">
                <p class="text-accent-deep font-medium text-sm">
                    ● Purchased {{ purchase.quantity }} {{ listing.unit }} — ${{ purchase.amount }} settled
                </p>
                <button @click="download"
                    class="bg-ink text-white px-4 py-2 rounded-lg text-sm hover:bg-ink/90">
                    Download dataset
                </button>
            </div>
        </div>
    </PageWrapper>
</template>
