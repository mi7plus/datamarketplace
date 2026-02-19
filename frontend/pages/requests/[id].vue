<script setup lang="ts">
import { ref } from 'vue'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import BackButton from '~/components/BackButton.vue'

const submissions = ref([
  { id: 's1', provider: 'Alice', data_amount: 100, status: 'pending', price: 50 },
  { id: 's2', provider: 'Bob', data_amount: 150, status: 'pending', price: 75 },
])

const selectedSubmissions = ref<string[]>([])
const budget = ref(200)

const toggleSelection = (id: string) => {
  if (selectedSubmissions.value.includes(id)) {
    selectedSubmissions.value = selectedSubmissions.value.filter(s => s !== id)
  } else {
    selectedSubmissions.value.push(id)
  }
}

const accept = async () => {
  try {
    const res = await $fetch(`/api/requests/1/accept`, {
      method: 'POST',
      body: { submission_ids: selectedSubmissions.value, budget: budget.value },
    })
    alert(`Accepted! Total data: ${res.total_data}, Cost: ${res.total_cost}`)
  } catch (err: any) {
    alert(err.data?.detail || 'Error accepting submissions')
  }
}
</script>

<template>
  <PageWrapper>
    <BackButton fallback="/requests" />
    <h1 class="text-2xl font-bold mb-4">Request #1 Submissions</h1>

    <div class="mb-4">
      <label>Budget: </label>
      <input type="number" v-model="budget" class="border px-2 py-1 w-32" />
    </div>

    <ul class="space-y-2">
      <li
          v-for="s in submissions"
          :key="s.id"
          class="border p-3 rounded flex justify-between items-center"
      >
        <div>
          <strong>{{ s.provider }}</strong> – {{ s.data_amount }} records – ${{ s.price }}
        </div>
        <div>
          <input type="checkbox" :value="s.id" v-model="selectedSubmissions" />
        </div>
      </li>
    </ul>

    <button @click="accept" class="mt-4 px-4 py-2 bg-blue-600 text-white rounded">
      Accept Selected
    </button>
  </PageWrapper>
</template>