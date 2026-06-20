<script setup lang="ts">
import type { DataRequest } from '~/composables/useRequests'

const props = defineProps<DataRequest>()

const fillPct = computed(() => {
    if (!props.amount_required || !props.accepted_total) return 0
    return Math.min(100, Math.round((props.accepted_total / props.amount_required) * 100))
})

const statusColour: Record<string, string> = {
    draft: 'bg-gray-100 text-gray-600',
    open: 'bg-blue-100 text-blue-700',
    partially_fulfilled: 'bg-yellow-100 text-yellow-700',
    completed: 'bg-green-100 text-green-700',
    expired: 'bg-red-100 text-red-500',
    review: 'bg-purple-100 text-purple-700',
}
</script>

<template>
    <NuxtLink :to="`/requests/${id}`"
        class="block border rounded-lg p-4 bg-white hover:shadow transition">
        <div class="flex justify-between items-start gap-4">
            <div class="flex-1 min-w-0">
                <h3 class="text-lg font-semibold truncate">{{ title }}</h3>
                <p class="text-gray-500 text-sm mt-1 line-clamp-2">{{ description }}</p>
            </div>
            <div class="text-right shrink-0">
                <div class="font-bold text-lg">${{ budget?.toLocaleString() ?? '—' }}</div>
                <div class="text-xs text-gray-400 mt-0.5">
                    {{ price_per_unit ? `$${price_per_unit}/${unit ?? 'unit'}` : 'fixed bounty' }}
                </div>
                <span class="inline-block mt-1 text-xs px-2 py-0.5 rounded-full"
                    :class="statusColour[status] ?? 'bg-gray-100 text-gray-600'">
                    {{ status.replace('_', ' ') }}
                </span>
            </div>
        </div>

        <!-- Fulfilment progress -->
        <div class="mt-3">
            <div class="flex justify-between text-xs text-gray-500 mb-1">
                <span>{{ accepted_total?.toLocaleString() ?? 0 }} / {{ amount_required?.toLocaleString() ?? '?' }} {{ unit ?? 'units' }}</span>
                <span>{{ fillPct }}% filled</span>
            </div>
            <div class="h-2 bg-surface-border rounded">
                <div class="h-2 bg-accent-deep rounded transition-all"
                    :style="{ width: fillPct + '%' }" />
            </div>
        </div>
    </NuxtLink>
</template>
