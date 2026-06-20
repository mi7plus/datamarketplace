<script setup lang="ts">
import RequestCard from '~/components/requests/RequestCard.vue'
import { useRequests } from '~/composables/useRequests'
import PageWrapper from '~/components/layout/PageWrapper.vue'

const { requests, loading, error } = useRequests()

const filterStatus = ref('all')
const filterUnit = ref('all')

// Distinct units present, for the unit filter.
const units = computed(() => {
    const set = new Set<string>()
    for (const r of requests.value) if (r.unit) set.add(r.unit)
    return ['all', ...Array.from(set).sort()]
})

const filtered = computed(() =>
    requests.value.filter(r =>
        (filterStatus.value === 'all' || r.status === filterStatus.value) &&
        (filterUnit.value === 'all' || r.unit === filterUnit.value)
    )
)
</script>

<template>
    <PageWrapper>
        <div class="flex items-center justify-between mb-6">
            <h1 class="text-2xl font-bold text-ink">Browse Data Requests</h1>
            <NuxtLink to="/requests/create"
                class="text-sm bg-ink text-white px-4 py-2 rounded-lg hover:bg-ink/90 transition-colors">
                + New Request
            </NuxtLink>
        </div>

        <!-- Filters -->
        <div class="space-y-2 mb-4">
            <div class="flex gap-2 flex-wrap items-center">
                <span class="text-xs text-surface-label uppercase tracking-wide w-14">Status</span>
                <button v-for="s in ['all', 'open', 'partially_fulfilled', 'completed', 'expired']" :key="s"
                    @click="filterStatus = s"
                    class="text-xs px-3 py-1 rounded-full border transition-colors"
                    :class="filterStatus === s ? 'bg-ink text-white border-ink' : 'text-muted border-surface-border hover:border-accent'">
                    {{ s === 'all' ? 'All' : s.replace(/_/g, ' ') }}
                </button>
            </div>
            <div v-if="units.length > 1" class="flex gap-2 flex-wrap items-center">
                <span class="text-xs text-surface-label uppercase tracking-wide w-14">Unit</span>
                <button v-for="u in units" :key="u"
                    @click="filterUnit = u"
                    class="text-xs px-3 py-1 rounded-full border transition-colors"
                    :class="filterUnit === u ? 'bg-accent-deep text-white border-accent-deep' : 'text-muted border-surface-border hover:border-accent'">
                    {{ u === 'all' ? 'All' : u }}
                </button>
            </div>
        </div>

        <div v-if="loading" class="text-gray-400 text-sm py-8 text-center">Loading requests…</div>
        <div v-else-if="error" class="text-red-500 text-sm py-8 text-center">{{ error }}</div>
        <div v-else-if="filtered.length === 0" class="text-gray-400 text-sm py-8 text-center">
            No requests found.
        </div>

        <div v-else class="grid gap-4">
            <RequestCard v-for="req in filtered" :key="req.id" v-bind="req" />
        </div>
    </PageWrapper>
</template>
