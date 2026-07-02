<script setup lang="ts">
// Wrapper for every admin page: a persistent "privileged context" banner (design §6
// — an admin should always know they're acting on someone else's data) plus nav.
import { useAdmin } from '~/composables/useAdmin'

const { me } = useAdmin()
const links = [
  { to: '/admin', label: 'Dashboard' },
  { to: '/admin/users', label: 'Users' },
  { to: '/admin/audit', label: 'Audit log' },
]
</script>

<template>
  <div>
    <div class="mb-4 rounded bg-amber-100 border border-amber-300 text-amber-900 px-4 py-2 text-sm flex items-center justify-between">
      <span>⚠️ Admin panel — privileged access to customer data. Every action is audited.</span>
      <span v-if="me" class="font-medium">{{ me.email }} · {{ me.admin_role }}</span>
    </div>
    <nav class="flex gap-4 mb-6 border-b pb-2 text-sm">
      <NuxtLink
        v-for="l in links" :key="l.to" :to="l.to"
        class="text-gray-600 hover:text-teal-700"
        active-class="text-teal-700 font-semibold"
      >{{ l.label }}</NuxtLink>
    </nav>
    <slot />
  </div>
</template>
