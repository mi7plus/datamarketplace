<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import BackButton from '~/components/BackButton.vue'
import SubmissionForm from '~/components/requests/SubmissionForm.vue'
import DownloadButton from '~/components/submissions/DownloadButton.vue'
import DisputeButton from '~/components/submissions/DisputeButton.vue'
import ReviewForm from '~/components/submissions/ReviewForm.vue'
import { useRequests } from '~/composables/useRequests'
import { useAuthStore } from '~/stores/auth'
import { useApi } from '~/composables/useApi'
import { useRuntimeConfig } from '#app'

const route = useRoute()
const { fetchRequest } = useRequests()
const auth = useAuthStore()
const api = useApi()
const config = useRuntimeConfig()

const request = ref<any>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const submissions = ref<any[]>([])
const actionError = ref<string | null>(null)
const actioning = ref<string | null>(null)  // submission id being actioned
const ledger = ref<any>(null)
const funding = ref(false)

async function loadRequest() {
    const data = await fetchRequest(route.params.id as string)
    if (data) request.value = data
    else error.value = 'Request not found'
}

async function loadSubmissions() {
    try {
        submissions.value = await api.get(`/submissions/request/${route.params.id}`)
    } catch { /* visitor or provider — no access to buyer list */ }
}

onMounted(async () => {
    await loadRequest()
    if (request.value) await Promise.all([loadSubmissions(), loadLedger()])
    loading.value = false
})

async function doAction(submissionId: string, action: 'accept' | 'reject') {
    actioning.value = submissionId
    actionError.value = null
    try {
        const res = await fetch(
            `${config.public.apiBase}/submissions/${submissionId}/${action}`,
            { method: 'POST', headers: { Authorization: `Bearer ${auth.token}` } }
        )
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || `${action} failed`)
        // Refresh both to get updated accepted_total on the request
        await Promise.all([loadRequest(), loadSubmissions()])
    } catch (e: any) {
        actionError.value = e.message
    } finally {
        actioning.value = null
    }
}

async function confirmSubmission(submissionId: string) {
    actioning.value = submissionId
    actionError.value = null
    try {
        await api.post(`/submissions/${submissionId}/confirm`, {})
        await Promise.all([loadRequest(), loadSubmissions(), loadLedger()])
    } catch (e: any) {
        actionError.value = e.message
    } finally {
        actioning.value = null
    }
}

// Human-readable acceptance-window countdown from a submission's confirm_by.
function windowRemaining(confirmBy: string | null): string | null {
    if (!confirmBy) return null
    const ms = new Date(confirmBy).getTime() - Date.now()
    if (ms <= 0) return 'window elapsed — auto-release pending'
    const h = Math.floor(ms / 3.6e6)
    const m = Math.floor((ms % 3.6e6) / 6e4)
    return (h > 0 ? `${h}h ${m}m` : `${m}m`) + ' left to confirm or dispute'
}

async function expireRequest() {
    if (!confirm('Close this request and refund unspent budget?')) return
    actionError.value = null
    try {
        await fetch(
            `${config.public.apiBase}/submissions/requests/${request.value.id}/expire`,
            { method: 'POST', headers: { Authorization: `Bearer ${auth.token}` } }
        )
        await Promise.all([loadRequest(), loadLedger()])
    } catch (e: any) {
        actionError.value = e.message
    }
}

async function fundRequest() {
    if (!confirm(`Fund this request and hold $${request.value.budget?.toLocaleString()} in escrow?`)) return
    funding.value = true
    actionError.value = null
    try {
        const res = await fetch(
            `${config.public.apiBase}/requests/${request.value.id}/fund`,
            { method: 'POST', headers: { Authorization: `Bearer ${auth.token}` } }
        )
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || 'Fund failed')
        await Promise.all([loadRequest(), loadLedger()])
    } catch (e: any) {
        actionError.value = e.message
    } finally {
        funding.value = false
    }
}

async function loadLedger() {
    if (auth.user?.role !== 'requester') return
    try {
        ledger.value = await api.get(`/requests/${route.params.id}/ledger`)
    } catch { /* only requester can see ledger */ }
}

const fillPct = computed(() => {
    if (!request.value?.amount_required || !request.value?.accepted_total) return 0
    return Math.min(100, Math.round((request.value.accepted_total / request.value.amount_required) * 100))
})

const remaining = computed(() =>
    (request.value?.amount_required ?? 0) - (request.value?.accepted_total ?? 0)
)

const validatedSubmissions = computed(() =>
    submissions.value.filter(s => s.status === 'validated')
)

const decidedSubmissions = computed(() =>
    submissions.value.filter(s => s.status !== 'validated')
)

const statusColour: Record<string, string> = {
    draft: 'bg-gray-100 text-gray-600',
    open: 'bg-blue-100 text-blue-700',
    partially_fulfilled: 'bg-yellow-100 text-yellow-700',
    completed: 'bg-green-100 text-green-700',
    expired: 'bg-red-100 text-red-500',
    review: 'bg-purple-100 text-purple-700',
}

const subColour: Record<string, string> = {
    validated: 'bg-blue-100 text-blue-700',
    accepted: 'bg-green-100 text-green-700',
    partially_accepted: 'bg-yellow-100 text-yellow-700',
    rejected: 'bg-red-100 text-red-500',
    rejected_invalid: 'bg-red-100 text-red-600',
    paid: 'bg-emerald-100 text-emerald-700',
    disputed: 'bg-orange-100 text-orange-700',
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
                <div class="flex flex-col items-end gap-2 shrink-0">
                    <span class="text-sm px-3 py-1 rounded-full"
                        :class="statusColour[request.status] ?? 'bg-gray-100 text-gray-600'">
                        {{ request.status.replace(/_/g, ' ') }}
                    </span>
                    <!-- Fund & Open (requester, DRAFT only) -->
                    <button
                        v-if="request.status === 'draft' && auth.user?.role === 'requester'"
                        @click="fundRequest"
                        :disabled="funding"
                        class="px-4 py-1.5 rounded bg-blue-600 text-white text-sm
                               hover:bg-blue-700 disabled:opacity-50">
                        {{ funding ? 'Processing…' : `Fund $${request.budget?.toLocaleString()} & Open` }}
                    </button>
                    <!-- Close early -->
                    <button
                        v-if="['open','partially_fulfilled'].includes(request.status) && auth.user?.role === 'requester'"
                        @click="expireRequest"
                        class="text-xs text-red-500 hover:underline">
                        Close & refund
                    </button>
                </div>
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
                    <template v-if="request.license_name">
                        <dt class="text-gray-500">License</dt>
                        <dd>{{ request.license_name }}</dd>
                    </template>
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

            <!-- ============================================================
                 ESCROW LEDGER (requester only)
                 ============================================================ -->
            <div v-if="ledger" class="border rounded-lg p-4 bg-white space-y-3">
                <h2 class="font-semibold text-sm text-gray-700 uppercase tracking-wide">Escrow</h2>
                <dl class="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-1 text-sm">
                    <dt class="text-gray-500">Held</dt>
                    <dd class="font-medium">${{ ledger.balance.held?.toLocaleString() }}</dd>
                    <dt class="text-gray-500">Released</dt>
                    <dd class="text-green-700">${{ ledger.balance.released?.toLocaleString() }}</dd>
                    <dt class="text-gray-500">Refunded</dt>
                    <dd class="text-blue-700">${{ ledger.balance.refunded?.toLocaleString() }}</dd>
                    <dt class="text-gray-500">Remaining</dt>
                    <dd class="font-semibold">${{ ledger.balance.remaining?.toLocaleString() }}</dd>
                </dl>
                <details class="text-xs">
                    <summary class="cursor-pointer text-gray-500 hover:text-gray-700">
                        Ledger entries ({{ ledger.entries.length }})
                    </summary>
                    <div class="mt-2 divide-y">
                        <div v-for="e in ledger.entries" :key="e.id"
                            class="flex justify-between py-1 text-gray-600">
                            <span class="capitalize font-medium" :class="{
                                'text-gray-700': e.type === 'hold',
                                'text-green-700': e.type === 'release',
                                'text-blue-700': e.type === 'refund',
                            }">{{ e.type }}</span>
                            <span>${{ e.amount }}</span>
                            <span class="text-gray-400 font-mono">{{ e.external_ref?.slice(0, 20) }}</span>
                        </div>
                    </div>
                </details>
            </div>

            <!-- ============================================================
                 BUYER REVIEW — VALIDATED submissions awaiting decision
                 ============================================================ -->
            <div v-if="validatedSubmissions.length" class="space-y-3">
                <h2 class="font-semibold text-sm text-gray-700 uppercase tracking-wide">
                    Awaiting Review ({{ validatedSubmissions.length }})
                </h2>

                <p v-if="actionError" class="text-red-500 text-sm">{{ actionError }}</p>

                <div v-for="s in validatedSubmissions" :key="s.id"
                    class="border-2 border-blue-200 rounded-lg p-4 bg-blue-50 space-y-3">

                    <div class="flex justify-between items-start gap-2">
                        <div class="text-xs font-mono text-gray-400">{{ s.id.slice(0, 8) }}…</div>
                        <div class="flex items-center gap-1.5 flex-wrap justify-end">
                            <span v-if="s.quality_score != null"
                                class="text-xs px-2 py-0.5 rounded-full bg-accent/15 text-accent-deep">
                                Quality {{ Math.round(s.quality_score * 100) }}%
                            </span>
                            <span v-if="s.pii_report?.risk && s.pii_report.risk !== 'none'"
                                class="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">
                                PII: {{ s.pii_report.risk }}
                            </span>
                            <span v-if="s.quarantined"
                                class="text-xs px-2 py-0.5 rounded-full bg-orange-100 text-orange-700">
                                under review
                            </span>
                            <span class="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">validated</span>
                        </div>
                    </div>

                    <!-- Validation summary -->
                    <dl class="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-1 text-sm">
                        <dt class="text-gray-500">Offered</dt>
                        <dd class="font-medium">{{ s.offered_amount?.toLocaleString() }} {{ request.unit }}</dd>
                        <dt class="text-gray-500">Validated</dt>
                        <dd class="font-medium text-blue-700">{{ s.validated_amount?.toLocaleString() }} {{ request.unit }}</dd>
                        <dt class="text-gray-500">Remaining capacity</dt>
                        <dd class="font-medium text-green-700">{{ remaining.toLocaleString() }} {{ request.unit }}</dd>
                        <dt class="text-gray-500">Would accept</dt>
                        <dd class="font-medium">
                            {{ Math.min(s.validated_amount ?? 0, remaining).toLocaleString() }} {{ request.unit }}
                            <span v-if="(s.validated_amount ?? 0) > remaining" class="text-xs text-yellow-600 ml-1">
                                (capped — over-delivery)
                            </span>
                        </dd>
                    </dl>

                    <!-- Sample data preview -->
                    <details v-if="s.validation_report?.sample?.length" class="text-xs">
                        <summary class="cursor-pointer text-blue-700 hover:underline">
                            Preview sample ({{ s.validation_report.sample.length }} rows)
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
                                            class="border px-2 py-1 font-mono">
                                            {{ val }}
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </details>

                    <!-- Accept / Reject buttons -->
                    <div class="flex gap-3 pt-1">
                        <button
                            @click="doAction(s.id, 'accept')"
                            :disabled="actioning === s.id || remaining === 0"
                            class="px-4 py-1.5 rounded bg-green-600 text-white text-sm
                                   hover:bg-green-700 disabled:opacity-50">
                            {{ actioning === s.id ? 'Processing…' : 'Accept' }}
                        </button>
                        <button
                            @click="doAction(s.id, 'reject')"
                            :disabled="actioning === s.id"
                            class="px-4 py-1.5 rounded border border-red-300 text-red-600
                                   text-sm hover:bg-red-50 disabled:opacity-50">
                            Reject
                        </button>
                        <span v-if="remaining === 0" class="text-xs text-gray-400 self-center">
                            Target already met
                        </span>
                    </div>
                </div>
            </div>

            <!-- ============================================================
                 DECIDED submissions (accepted / rejected / paid / etc.)
                 ============================================================ -->
            <div v-if="decidedSubmissions.length" class="border rounded-lg p-4 bg-white space-y-3">
                <h2 class="font-semibold text-sm text-gray-700 uppercase tracking-wide">
                    Decided Submissions ({{ decidedSubmissions.length }})
                </h2>
                <div v-for="s in decidedSubmissions" :key="s.id"
                    class="border rounded p-3 space-y-2 text-sm">
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400 text-xs font-mono">{{ s.id.slice(0, 8) }}…</span>
                        <span class="text-xs px-2 py-0.5 rounded-full"
                            :class="subColour[s.status] ?? 'bg-gray-100 text-gray-600'">
                            {{ s.status.replace(/_/g, ' ') }}
                        </span>
                    </div>
                    <dl class="grid grid-cols-4 gap-x-4 gap-y-1 text-xs text-gray-600">
                        <dt>Offered</dt><dd>{{ s.offered_amount?.toLocaleString() }}</dd>
                        <dt>Validated</dt><dd>{{ s.validated_amount?.toLocaleString() ?? '—' }}</dd>
                        <dt>Accepted</dt><dd>{{ s.accepted_amount?.toLocaleString() ?? 0 }}</dd>
                        <dt>Amount due</dt><dd>{{ s.amount_due != null ? `$${s.amount_due}` : '—' }}</dd>
                    </dl>
                    <!-- Settlement state badges -->
                    <div class="flex items-center gap-1.5 flex-wrap">
                        <span v-if="s.quality_score != null" class="text-xs text-muted">
                            Quality {{ Math.round(s.quality_score * 100) }}%
                        </span>
                        <span v-if="s.quarantined" class="text-xs px-2 py-0.5 rounded-full bg-orange-100 text-orange-700">
                            under review
                        </span>
                    </div>

                    <!-- Acceptance window: escrow HELD, buyer confirms or disputes -->
                    <div v-if="['accepted','partially_accepted'].includes(s.status)"
                        class="pt-2 mt-1 border-t space-y-2">
                        <div class="flex items-center justify-between text-xs">
                            <span class="text-accent-deep font-medium">● Escrow held — awaiting confirmation</span>
                            <span v-if="windowRemaining(s.confirm_by)" class="text-muted">
                                {{ windowRemaining(s.confirm_by) }}
                            </span>
                        </div>
                        <div class="flex flex-wrap gap-3 items-center">
                            <button v-if="auth.user?.role === 'requester'"
                                @click="confirmSubmission(s.id)"
                                :disabled="actioning === s.id"
                                class="px-4 py-1.5 rounded bg-accent-deep text-white text-sm hover:bg-accent disabled:opacity-50">
                                {{ actioning === s.id ? 'Releasing…' : 'Confirm & release escrow' }}
                            </button>
                            <!-- Buyer may inspect the full file before releasing (F4) -->
                            <DownloadButton :submission-id="s.id" />
                            <DisputeButton :submission-id="s.id" @disputed="loadSubmissions" />
                        </div>
                    </div>

                    <!-- Disputed: release paused pending admin -->
                    <div v-else-if="s.status === 'disputed'" class="pt-2 mt-1 border-t text-xs text-orange-700">
                        ⚠ Dispute open — escrow release paused pending admin resolution.
                    </div>

                    <!-- Settled: download + review -->
                    <div v-else-if="s.status === 'paid'" class="pt-2 mt-1 border-t flex flex-wrap gap-3 items-start">
                        <span class="text-xs text-accent-deep font-medium w-full">● Settled — escrow released to provider</span>
                        <DownloadButton :submission-id="s.id" />
                        <ReviewForm :submission-id="s.id" @reviewed="loadSubmissions" />
                    </div>
                </div>
            </div>

            <!-- ============================================================
                 PROVIDER: inline submission form
                 ============================================================ -->
            <SubmissionForm
                v-if="['open', 'partially_fulfilled'].includes(request.status)"
                :request-id="request.id"
                :request-spec="request.spec"
                :unit="request.unit"
                @submitted="loadSubmissions"
            />

        </div>
    </PageWrapper>
</template>
