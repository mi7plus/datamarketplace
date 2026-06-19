<script setup lang="ts">
import RequestCard from '~/components/requests/RequestCard.vue'
import { useRequests } from '~/composables/useRequests'
import PageWrapper from '~/components/layout/PageWrapper.vue'

const { requests, loading, error } = useRequests()

const filterStatus = ref('all')

const filtered = computed(() => {
    if (filterStatus.value === 'all') return requests.value
    return requests.value.filter(r => r.status === filterStatus.value)
})
</script>

<template>
    <PageWrapper>
        <div class="flex items-center justify-between mb-6">
            <h1 class="text-2xl font-bold">Browse Data Requests</h1>
            <NuxtLink to="/requests/create"
                class="text-sm bg-black text-white px-4 py-2 rounded hover:bg-gray-800">
                + New Request
            </NuxtLink>
        </div>

        <!-- Filters -->
        <div class="flex gap-2 mb-4 flex-wrap">
            <button v-for="s in ['all', 'open', 'partially_fulfilled', 'completed']" :key="s"
                @click="filterStatus = s"
                class="text-xs px-3 py-1 rounded-full border transition"
                :class="filterStatus === s ? 'bg-black text-white border-black' : 'text-gray-600 hover:border-gray-400'">
                {{ s === 'all' ? 'All' : s.replace('_', ' ') }}
            </button>
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
