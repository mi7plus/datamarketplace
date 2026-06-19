<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useApi } from '~/composables/useApi'

const router = useRouter()
const api = useApi()

const COLUMN_TYPES = ['string', 'integer', 'float', 'boolean', 'date', 'datetime'] as const

const form = ref({
    title: '',
    description: '',
    unit: 'row',
    amount_required: 1000,
    pricing_mode: 'per_unit' as 'per_unit' | 'fixed_bounty',
    price_per_unit: 0.1,
    budget: 0,
    required_format: 'csv' as 'csv' | 'jsonl',
    deadline: '',
})

const columns = ref([
    { name: '', type: 'string' as typeof COLUMN_TYPES[number], required: true },
])

const uniqueKey = ref('')   // comma-separated column names
const submitting = ref(false)
const serverError = ref<string | null>(null)

const computedBudget = computed(() =>
    form.value.pricing_mode === 'per_unit'
        ? (form.value.price_per_unit * form.value.amount_required).toFixed(2)
        : form.value.budget.toFixed(2)
)

function addColumn() {
    columns.value.push({ name: '', type: 'string', required: true })
}

function removeColumn(i: number) {
    columns.value.splice(i, 1)
}

async function submit() {
    serverError.value = null
    submitting.value = true
    try {
        const spec = {
            columns: columns.value.map(c => ({ name: c.name, type: c.type, required: c.required })),
            unique_key: uniqueKey.value
                ? uniqueKey.value.split(',').map(s => s.trim()).filter(Boolean)
                : undefined,
        }

        const payload: Record<string, any> = {
            title: form.value.title,
            description: form.value.description || undefined,
            unit: form.value.unit,
            amount_required: form.value.amount_required,
            pricing_mode: form.value.pricing_mode,
            required_format: form.value.required_format,
            spec,
            deadline: form.value.deadline || undefined,
        }

        if (form.value.pricing_mode === 'per_unit') {
            payload.price_per_unit = form.value.price_per_unit
        } else {
            payload.budget = form.value.budget
        }

        const created = await api.post('/requests/', payload)
        router.push(`/requests/${created.id}`)
    } catch (e: any) {
        serverError.value = e.message
    } finally {
        submitting.value = false
    }
}
</script>

<template>
    <form class="space-y-6 max-w-2xl" @submit.prevent="submit">

        <!-- Basic info -->
        <div class="space-y-3">
            <div>
                <label class="block text-sm font-medium mb-1">Title *</label>
                <input v-model="form.title" required placeholder="e.g. Street images for autonomous driving"
                    class="w-full border rounded px-3 py-2 text-sm" />
            </div>
            <div>
                <label class="block text-sm font-medium mb-1">Description</label>
                <textarea v-model="form.description" rows="3" placeholder="What data do you need and why?"
                    class="w-full border rounded px-3 py-2 text-sm" />
            </div>
        </div>

        <!-- Quantity + format -->
        <div class="grid grid-cols-2 gap-4">
            <div>
                <label class="block text-sm font-medium mb-1">Unit *</label>
                <input v-model="form.unit" required placeholder="row / record / image"
                    class="w-full border rounded px-3 py-2 text-sm" />
            </div>
            <div>
                <label class="block text-sm font-medium mb-1">Amount required *</label>
                <input v-model.number="form.amount_required" type="number" min="1" required
                    class="w-full border rounded px-3 py-2 text-sm" />
            </div>
            <div>
                <label class="block text-sm font-medium mb-1">Format *</label>
                <select v-model="form.required_format" class="w-full border rounded px-3 py-2 text-sm">
                    <option value="csv">CSV</option>
                    <option value="jsonl">JSONL</option>
                </select>
            </div>
            <div>
                <label class="block text-sm font-medium mb-1">Deadline</label>
                <input v-model="form.deadline" type="datetime-local"
                    class="w-full border rounded px-3 py-2 text-sm" />
            </div>
        </div>

        <!-- Pricing -->
        <div class="space-y-3">
            <div>
                <label class="block text-sm font-medium mb-1">Pricing mode *</label>
                <div class="flex gap-4">
                    <label class="flex items-center gap-2 text-sm">
                        <input type="radio" v-model="form.pricing_mode" value="per_unit" />
                        Per unit
                    </label>
                    <label class="flex items-center gap-2 text-sm">
                        <input type="radio" v-model="form.pricing_mode" value="fixed_bounty" />
                        Fixed bounty
                    </label>
                </div>
            </div>

            <div v-if="form.pricing_mode === 'per_unit'" class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm font-medium mb-1">Price per {{ form.unit || 'unit' }} ($) *</label>
                    <input v-model.number="form.price_per_unit" type="number" min="0.0001" step="0.0001" required
                        class="w-full border rounded px-3 py-2 text-sm" />
                </div>
                <div>
                    <label class="block text-sm font-medium mb-1">Total budget (derived)</label>
                    <div class="border rounded px-3 py-2 text-sm bg-gray-50 text-gray-600">
                        ${{ computedBudget }}
                    </div>
                </div>
            </div>

            <div v-else>
                <label class="block text-sm font-medium mb-1">Budget ($) *</label>
                <input v-model.number="form.budget" type="number" min="0.01" step="0.01" required
                    class="w-full border rounded px-3 py-2 text-sm" />
            </div>
        </div>

        <!-- Data spec -->
        <div>
            <div class="flex items-center justify-between mb-2">
                <label class="block text-sm font-medium">Data schema *</label>
                <button type="button" @click="addColumn"
                    class="text-xs text-blue-600 hover:underline">
                    + Add column
                </button>
            </div>

            <div class="space-y-2">
                <div v-for="(col, i) in columns" :key="i"
                    class="flex gap-2 items-center border rounded px-3 py-2">
                    <input v-model="col.name" placeholder="Column name" required
                        class="flex-1 border rounded px-2 py-1 text-sm" />
                    <select v-model="col.type" class="border rounded px-2 py-1 text-sm">
                        <option v-for="t in COLUMN_TYPES" :key="t" :value="t">{{ t }}</option>
                    </select>
                    <label class="flex items-center gap-1 text-xs whitespace-nowrap">
                        <input type="checkbox" v-model="col.required" />
                        Required
                    </label>
                    <button type="button" @click="removeColumn(i)"
                        class="text-red-400 hover:text-red-600 text-sm px-1"
                        :disabled="columns.length === 1">✕</button>
                </div>
            </div>

            <div class="mt-2">
                <label class="block text-xs text-gray-500 mb-1">
                    Unique key columns (comma-separated, optional — enables cross-provider dedup)
                </label>
                <input v-model="uniqueKey" placeholder="e.g. transaction_id"
                    class="w-full border rounded px-3 py-2 text-sm" />
            </div>
        </div>

        <p v-if="serverError" class="text-red-600 text-sm">{{ serverError }}</p>

        <button type="submit" :disabled="submitting"
            class="bg-black text-white px-6 py-2 rounded disabled:opacity-50">
            {{ submitting ? 'Creating…' : 'Create Request' }}
        </button>
    </form>
</template>
