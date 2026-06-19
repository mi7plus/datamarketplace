<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAuthStore } from '~/stores/auth'
import { useRuntimeConfig } from '#app'

const props = defineProps<{ requestId: string; requestSpec?: any; unit?: string }>()
const emit = defineEmits<{ submitted: [result: any] }>()

const auth = useAuthStore()
const config = useRuntimeConfig()

const file = ref<File | null>(null)
const offeredAmount = ref(100)
const submitting = ref(false)
const error = ref<string | null>(null)
const result = ref<any>(null)

const fileError = computed(() => {
    if (!file.value) return null
    const ext = file.value.name.split('.').pop()?.toLowerCase()
    if (!['csv', 'jsonl'].includes(ext ?? '')) return 'Only CSV and JSONL files are accepted'
    if (file.value.size > 100 * 1024 * 1024) return 'File must be under 100 MB'
    return null
})

function onFileChange(e: Event) {
    const input = e.target as HTMLInputElement
    file.value = input.files?.[0] ?? null
    result.value = null
    error.value = null
}

async function submit() {
    if (!file.value || fileError.value) return
    submitting.value = true
    error.value = null
    result.value = null

    try {
        const fd = new FormData()
        fd.append('request_id', props.requestId)
        fd.append('offered_amount', String(offeredAmount.value))
        fd.append('file', file.value)

        const res = await fetch(`${config.public.apiBase}/submissions/`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${auth.token}` },
            body: fd,
        })

        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || `Error ${res.status}`)

        result.value = data
        emit('submitted', data)
    } catch (e: any) {
        error.value = e.message
    } finally {
        submitting.value = false
    }
}
</script>

<template>
    <div class="border rounded-lg p-5 bg-white space-y-4">
        <h3 class="font-semibold text-lg">Submit Data</h3>

        <!-- Schema reminder -->
        <div v-if="requestSpec?.columns?.length" class="text-xs text-gray-500 bg-gray-50 rounded p-3">
            <span class="font-medium text-gray-700">Expected columns: </span>
            <span v-for="(col, i) in requestSpec.columns" :key="col.name">
                <code>{{ col.name }}</code>
                <span class="text-gray-400"> ({{ col.type }}{{ col.required ? '' : ', optional' }})</span>{{ i < requestSpec.columns.length - 1 ? ', ' : '' }}
            </span>
        </div>

        <div>
            <label class="block text-sm font-medium mb-1">
                Upload file (CSV or JSONL) *
            </label>
            <input type="file" accept=".csv,.jsonl" @change="onFileChange"
                class="block w-full text-sm text-gray-600 file:mr-3 file:py-1 file:px-3
                       file:rounded file:border file:border-gray-300 file:text-sm
                       file:bg-white hover:file:bg-gray-50" />
            <p v-if="fileError" class="text-red-500 text-xs mt-1">{{ fileError }}</p>
            <p v-else-if="file" class="text-gray-400 text-xs mt-1">
                {{ file.name }} — {{ (file.size / 1024).toFixed(1) }} KB
            </p>
        </div>

        <div>
            <label class="block text-sm font-medium mb-1">
                Offered amount ({{ unit ?? 'units' }}) *
            </label>
            <input v-model.number="offeredAmount" type="number" min="1"
                class="w-40 border rounded px-3 py-2 text-sm" />
        </div>

        <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>

        <button @click="submit" :disabled="submitting || !file || !!fileError"
            class="bg-blue-600 text-white px-5 py-2 rounded disabled:opacity-50 hover:bg-blue-700 text-sm">
            {{ submitting ? 'Validating & uploading…' : 'Submit Dataset' }}
        </button>

        <!-- Validation result -->
        <div v-if="result" class="rounded border p-4 space-y-2 text-sm"
            :class="result.validated_amount > 0 ? 'border-green-300 bg-green-50' : 'border-red-300 bg-red-50'">
            <p class="font-medium" :class="result.validated_amount > 0 ? 'text-green-700' : 'text-red-700'">
                {{ result.validated_amount > 0 ? '✓ Submission validated' : '✗ Validation failed' }}
            </p>
            <div class="grid grid-cols-2 gap-x-6 gap-y-1 text-gray-600">
                <span>Status</span><span class="font-mono">{{ result.status }}</span>
                <span>Total rows</span><span>{{ result.validation_report?.total_rows }}</span>
                <span>Conforming rows</span><span class="font-medium">{{ result.validated_amount }}</span>
                <span>Rejected rows</span><span>{{ result.validation_report?.rejected_rows }}</span>
                <span v-if="result.validation_report?.duplicate_rows">Duplicate rows (skipped)</span>
                <span v-if="result.validation_report?.duplicate_rows">{{ result.validation_report.duplicate_rows }}</span>
            </div>
            <div v-if="result.validation_report?.row_errors?.length" class="mt-2">
                <p class="text-xs font-medium text-red-700 mb-1">Sample errors:</p>
                <ul class="text-xs text-red-600 space-y-0.5">
                    <li v-for="e in result.validation_report.row_errors.slice(0, 3)" :key="e.row">
                        Row {{ e.row }}: {{ e.errors.join('; ') }}
                    </li>
                </ul>
            </div>
        </div>
    </div>
</template>
