<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useApi } from '~/composables/useApi'
import AdminShell from '~/components/admin/AdminShell.vue'

definePageMeta({ middleware: ['admin'] })

const metrics = ref<any>(null)
const error = ref('')

onMounted(async () => {
  try {
    metrics.value = await useApi().get('/metrics/beachhead')
  } catch (e: any) {
    error.value = e.message || 'Failed to load metrics'
  }
})

const cards = () => metrics.value ? [
  { label: 'GMV', value: metrics.value.gmv },
  { label: 'Platform take', value: metrics.value.take },
  { label: 'Fill rate', value: `${Math.round((metrics.value.fill_rate || 0) * 100)}%` },
  { label: 'Total requests', value: metrics.value.requests?.total ?? 0 },
  { label: 'Buyers', value: metrics.value.buyers ?? 0 },
  { label: 'Repeat-buyer rate', value: `${Math.round((metrics.value.repeat_buyer_rate || 0) * 100)}%` },
] : []
</script>

<template>
  <AdminShell>
    <h1 class="text-2xl font-bold mb-6">Marketplace health</h1>
    <p v-if="error" class="text-red-600 mb-4">{{ error }}</p>
    <div v-if="metrics" class="grid grid-cols-2 md:grid-cols-3 gap-4">
      <div v-for="c in cards()" :key="c.label" class="bg-white rounded-lg shadow p-5">
        <div class="text-sm text-gray-500">{{ c.label }}</div>
        <div class="text-2xl font-semibold mt-1">{{ c.value }}</div>
      </div>
    </div>
    <p v-else-if="!error" class="text-gray-500">Loading…</p>
  </AdminShell>
</template>
