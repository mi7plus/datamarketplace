<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import BackButton from '~/components/BackButton.vue'
import { useRequests } from '~/composables/useRequests'

const route = useRoute()
const { fetchRequest } = useRequests()

const request = ref<any>(null)
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
    const data = await fetchRequest(route.params.id as string)
    if (data) {
        request.value = data
    } else {
        error.value = 'Request not found'
    }
    loading.value = false
})

const fillPct = computed(() => {
    if (!request.value?.amount_required || !request.value?.accepted_total) return 0
    return Math.min(100, Math.round((request.value.accepted_total / request.value.amount_required) * 100))
})

const remaining = computed(() => {
    if (!request.value) return 0
    return (request.value.amount_required ?? 0) - (request.value.accepted_total ?? 0)
})

const statusColour: Record<string, string> = {
    draft: 'bg-gray-100 text-gray-600',
    open: 'bg-blue-100 text-blue-700',
    partially_fulfilled: 'bg-yellow-100 text-yellow-700',
    completed: 'bg-green-100 text-green-700',
    expired: 'bg-red-100 text-red-500',
}
</script>

<template>
    <PageWrapper>
        <BackButton fallback="/requests" />

        <div v-if="loading" class="text-gray-400 text-sm py-12 text-center">Loading…</div>
        <div v-else-if="error" class="text-red-500 text-sm py-12 text-center">{{ error }}</div>

        <div v-else-if="request" class="space-y-6 max-w-3xl">

            <!-- Header -->
            <div class="flex items-start justify-between gap-4">
                <div>
                    <h1 class="text-2xl font-bold">{{ request.title }}</h1>
                    <p v-if="request.description" class="text-gray-500 mt-2">{{ request.description }}</p>
                </div>
                <span class="text-sm px-3 py-1 rounded-full shrink-0 mt-1"
                    :class="statusColour[request.status] ?? 'bg-gray-100 text-gray-600'">
                    {{ request.status.replace('_', ' ') }}
                </span>
            </div>

            <!-- Fulfilment progress -->
            <div class="border rounded-lg p-4 bg-white space-y-3">
                <h2 class="font-semibold text-sm text-gray-700 uppercase tracking-wide">Fulfilment</h2>
                <div class="flex justify-between text-sm">
                    <span>
                        <strong>{{ request.accepted_total?.toLocaleString() ?? 0 }}</strong>
                        / {{ request.amount_required?.toLocaleString() }} {{ request.unit ?? 'units' }} accepted
                    </span>
                    <span class="text-gray-500">{{ fillPct }}%</span>
                </div>
                <div class="h-3 bg-gray-200 rounded">
                    <div class="h-3 bg-green-500 rounded transition-all" :style="{ width: fillPct + '%' }" />
                </div>
                <p class="text-sm text-gray-500">
                    <strong>{{ remaining.toLocaleString() }}</strong> {{ request.unit ?? 'units' }} still needed
                </p>
            </div>

            <!-- Pricing -->
            <div class="border rounded-lg p-4 bg-white">
                <h2 class="font-semibold text-sm text-gray-700 uppercase tracking-wide mb-3">Pricing</h2>
                <dl class="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
                    <dt class="text-gray-500">Total budget</dt>
                    <dd class="font-medium">${{ request.budget?.toLocaleString() ?? '—' }}</dd>
                    <dt class="text-gray-500">Pricing mode</dt>
                    <dd>{{ request.pricing_mode?.replace('_', ' ') }}</dd>
                    <template v-if="request.pricing_mode === 'per_unit'">
                        <dt class="text-gray-500">Price per {{ request.unit ?? 'unit' }}</dt>
                        <dd>${{ request.price_per_unit }}</dd>
                    </template>
                    <template v-if="request.deadline">
                        <dt class="text-gray-500">Deadline</dt>
                        <dd>{{ new Date(request.deadline).toLocaleString() }}</dd>
                    </template>
                    <dt class="text-gray-500">Format</dt>
                    <dd class="uppercase">{{ request.required_format }}</dd>
                </dl>
            </div>

            <!-- Data schema spec -->
            <div v-if="request.spec?.columns?.length" class="border rounded-lg p-4 bg-white">
                <h2 class="font-semibold text-sm text-gray-700 uppercase tracking-wide mb-3">Data Schema</h2>
                <table class="w-full text-sm">
                    <thead>
                        <tr class="text-left text-gray-500 border-b">
                            <th class="pb-2 font-medium">Column</th>
                            <th class="pb-2 font-medium">Type</th>
                            <th class="pb-2 font-medium">Required</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="col in request.spec.columns" :key="col.name" class="border-b last:border-0">
                            <td class="py-2 font-mono text-xs">{{ col.name }}</td>
                            <td class="py-2 text-gray-600">{{ col.type }}</td>
                            <td class="py-2">
                                <span v-if="col.required" class="text-green-600 text-xs">✓ yes</span>
                                <span v-else class="text-gray-400 text-xs">optional</span>
                            </td>
                        </tr>
                    </tbody>
                </table>
                <p v-if="request.spec.unique_key?.length" class="mt-3 text-xs text-gray-500">
                    Unique key: <span class="font-mono">{{ request.spec.unique_key.join(', ') }}</span>
                    — cross-provider dedup enabled
                </p>
            </div>

            <!-- Submit data CTA (providers) -->
            <div class="border rounded-lg p-4 bg-blue-50">
                <p class="text-sm text-blue-800">
                    Have data that matches this spec?
                    <strong>{{ remaining.toLocaleString() }} {{ request.unit ?? 'units' }}</strong> still needed.
                </p>
                <NuxtLink :to="`/submissions?request=${request.id}`"
                    class="inline-block mt-2 text-sm bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">
                    Submit Data
                </NuxtLink>
            </div>

        </div>
    </PageWrapper>
</template>
