<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useApi } from '~/composables/useApi'
import AdminShell from '~/components/admin/AdminShell.vue'

definePageMeta({ middleware: ['admin'] })

const rows = ref<any[]>([])
const action = ref('')

const load = async () => {
  const qs = action.value ? `?action=${encodeURIComponent(action.value)}&limit=200` : '?limit=200'
  rows.value = await useApi().get(`/metrics/audit${qs}`)
}
onMounted(load)
</script>

<template>
  <AdminShell>
    <h1 class="text-2xl font-bold mb-4">Audit log</h1>
    <form class="flex gap-2 mb-4" @submit.prevent="load">
      <input v-model="action" placeholder="Filter by action (e.g. admin.txn_refund)…"
             class="border rounded px-3 py-2 flex-1 focus:ring-2 focus:ring-teal-500 outline-none" />
      <button class="bg-teal-600 text-white px-4 rounded hover:bg-teal-700">Filter</button>
    </form>
    <div class="bg-white rounded-lg shadow overflow-x-auto">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-left text-gray-500">
          <tr>
            <th class="p-3">When</th><th class="p-3">Action</th>
            <th class="p-3">Actor</th><th class="p-3">Target</th><th class="p-3">Meta</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id" class="border-t align-top">
            <td class="p-3 whitespace-nowrap text-gray-500">{{ r.created_at?.replace('T', ' ').slice(0, 19) }}</td>
            <td class="p-3 font-medium">{{ r.action }}</td>
            <td class="p-3 text-xs text-gray-500">{{ r.actor_id?.slice(0, 8) || '—' }}</td>
            <td class="p-3 text-xs">{{ r.object_type }}:{{ r.object_id?.slice(0, 8) }}</td>
            <td class="p-3 text-xs text-gray-600"><code>{{ r.meta ? JSON.stringify(r.meta) : '' }}</code></td>
          </tr>
          <tr v-if="!rows.length"><td colspan="5" class="p-4 text-center text-gray-400">No entries</td></tr>
        </tbody>
      </table>
    </div>
  </AdminShell>
</template>
