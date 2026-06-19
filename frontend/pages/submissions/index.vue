<script setup lang="ts">
import { ref, onMounted } from 'vue'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import BackButton from '~/components/BackButton.vue'
import { useApi } from '~/composables/useApi'

definePageMeta({ middleware: 'auth' })

const api = useApi()
const submissions = ref<any[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
    try {
        submissions.value = await api.get('/submissions/my')
    } catch (e: any) {
        error.value = e.message
    } finally {
        loading.value = false
    }
})

const statusColour: Record<string, string> = {
    pending: 'bg-gray-100 text-gray-600',
    validated: 'bg-blue-100 text-blue-700',
    rejected_invalid: 'bg-red-100 text-red-600',
    accepted: 'bg-green-100 text-green-700',
    partially_accepted: 'bg-yellow-100 text-yellow-700',
    rejected: 'bg-red-100 text-red-500',
    paid: 'bg-emerald-100 text-emerald-700',
    disputed: 'bg-orange-100 text-orange-700',
}
</script>

<template>
    <PageWrapper>
        <BackButton fallback="/" />
        <h1 class="text-2xl font-bold mb-6">My Submissions</h1>

        <div v-if="loading" class="text-gray-400 text-sm py-8 text-center">Loading…</div>
        <div v-else-if="error" class="text-red-500 text-sm py-8 text-center">{{ error }}</div>
        <div v-else-if="submissions.length === 0" class="text-gray-400 text-sm py-8 text-center">
            No submissions yet. Browse <NuxtLink to="/requests" class="underline">open requests</NuxtLink> to get started.
        </div>

        <div v-else class="space-y-4">
            <div v-for="s in submissions" :key="s.id"
                class="border rounded-lg p-4 bg-white space-y-2">
                <div class="flex items-start justify-between gap-4">
                    <div>
                        <NuxtLink :to="`/requests/${s.request_id}`"
                            class="text-sm font-medium text-blue-700 hover:underline">
                            View Request →
                        </NuxtLink>
                        <p class="text-xs text-gray-400 mt-0.5">
                            {{ s.created_at ? new Date(s.created_at).toLocaleString() : '—' }}
                        </p>
                    </div>
                    <span class="text-xs px-2 py-0.5 rounded-full shrink-0"
                        :class="statusColour[s.status] ?? 'bg-gray-100 text-gray-600'">
                        {{ s.status.replace('_', ' ') }}
                    </span>
                </div>

                <dl class="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-sm">
                    <dt class="text-gray-500">Offered</dt>
                    <dd>{{ s.offered_amount?.toLocaleString() }}</dd>
                    <dt class="text-gray-500">Validated</dt>
                    <dd>{{ s.validated_amount?.toLocaleString() ?? '—' }}</dd>
                    <dt class="text-gray-500">Accepted</dt>
                    <dd>{{ s.accepted_amount?.toLocaleString() ?? 0 }}</dd>
                    <dt class="text-gray-500">Amount due</dt>
                    <dd>{{ s.amount_due != null ? `$${s.amount_due}` : '—' }}</dd>
                </dl>

                <!-- Validation report summary -->
                <details v-if="s.validation_report" class="text-xs text-gray-500 mt-1">
                    <summary class="cursor-pointer hover:text-gray-700">Validation report</summary>
                    <div class="mt-2 bg-gray-50 rounded p-3 space-y-1">
                        <div>Total rows: {{ s.validation_report.total_rows }}</div>
                        <div>Conforming: {{ s.validation_report.conforming_rows }}</div>
                        <div>Rejected: {{ s.validation_report.rejected_rows }}</div>
                        <div v-if="s.validation_report.duplicate_rows">
                            Duplicates skipped: {{ s.validation_report.duplicate_rows }}
                        </div>
                        <div v-if="s.validation_report.row_errors?.length" class="text-red-600 mt-1">
                            <div v-for="e in s.validation_report.row_errors.slice(0,3)" :key="e.row">
                                Row {{ e.row }}: {{ e.errors.join('; ') }}
                            </div>
                        </div>
                    </div>
                </details>

                <!-- Disputed badge -->
                <p v-if="s.status === 'disputed'" class="text-xs text-orange-600 font-medium">
                    ⚠ A dispute is open on this submission — awaiting admin review.
                </p>

                <!-- Sample preview (visible to provider — same as what buyer sees) -->
                <details v-if="s.validation_report?.sample?.length" class="text-xs mt-1">
                    <summary class="cursor-pointer text-blue-600 hover:underline">
                        Sample preview ({{ s.validation_report.sample.length }} rows)
                    </summary>
                    <div class="overflow-x-auto mt-2">
                        <table class="text-xs border-collapse w-full">
                            <thead>
                                <tr class="bg-gray-100">
                                    <th v-for="k in Object.keys(s.validation_report.sample[0])" :key="k"
                                        class="border px-2 py-1 text-left font-mono font-normal text-gray-600">
                                        {{ k }}
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="(row, i) in s.validation_report.sample" :key="i">
                                    <td v-for="(val, key) in row" :key="key"
                                        class="border px-2 py-1 font-mono">{{ val }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <p class="text-gray-400 mt-1">This is what the buyer sees before payment.</p>
                </details>
            </div>
        </div>
    </PageWrapper>
</template>
