<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useApi } from '~/composables/useApi'
import AdminShell from '~/components/admin/AdminShell.vue'

definePageMeta({ middleware: ['admin'] })

const q = ref('')
const rows = ref<any[]>([])
const total = ref(0)
const loading = ref(false)

const load = async () => {
  loading.value = true
  try {
    const res = await useApi().get(`/admin/users?q=${encodeURIComponent(q.value)}&limit=50`)
    rows.value = res.users
    total.value = res.total
  } finally {
    loading.value = false
  }
}

onMounted(load)

const badge = (u: any) => {
  if (u.suspended) return { text: 'suspended', cls: 'bg-red-100 text-red-700' }
  if (u.account_locked) return { text: 'locked', cls: 'bg-amber-100 text-amber-800' }
  if (!u.is_verified) return { text: 'unverified', cls: 'bg-gray-100 text-gray-600' }
  return { text: 'active', cls: 'bg-green-100 text-green-700' }
}
</script>

<template>
  <AdminShell>
    <h1 class="text-2xl font-bold mb-4">Users</h1>
    <form class="flex gap-2 mb-4" @submit.prevent="load">
      <input v-model="q" placeholder="Search email…"
             class="border rounded px-3 py-2 flex-1 focus:ring-2 focus:ring-teal-500 outline-none" />
      <button class="bg-teal-600 text-white px-4 rounded hover:bg-teal-700">Search</button>
    </form>
    <p class="text-sm text-gray-500 mb-2">{{ total }} user(s)</p>
    <div class="bg-white rounded-lg shadow overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-left text-gray-500">
          <tr>
            <th class="p-3">Email</th><th class="p-3">Role</th>
            <th class="p-3">Admin</th><th class="p-3">Status</th><th class="p-3"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in rows" :key="u.id" class="border-t hover:bg-gray-50">
            <td class="p-3">{{ u.email }}</td>
            <td class="p-3">{{ u.role }}</td>
            <td class="p-3">{{ u.admin_role || '—' }}</td>
            <td class="p-3">
              <span :class="badge(u).cls" class="px-2 py-0.5 rounded text-xs">{{ badge(u).text }}</span>
            </td>
            <td class="p-3 text-right">
              <NuxtLink :to="`/admin/users/${u.id}`" class="text-teal-700 hover:underline">View</NuxtLink>
            </td>
          </tr>
          <tr v-if="!loading && !rows.length"><td colspan="5" class="p-4 text-gray-400 text-center">No users</td></tr>
        </tbody>
      </table>
    </div>
  </AdminShell>
</template>
