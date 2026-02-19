<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits(['submit'])

const form = ref({
  providerName: '',
  dataType: '',
  coverage: 0,
  price: 0,
  message: '',
})

const submit = () => {
  emit('submit', { ...form.value })
  form.value = {
    providerName: '',
    dataType: '',
    coverage: 0,
    price: 0,
    message: '',
  }
}
</script>

<template>
  <form @submit.prevent="submit" class="border rounded-lg p-4 space-y-4 bg-white">
    <h3 class="font-semibold">Submit Data</h3>

    <input v-model="form.providerName" class="input" placeholder="Your name or org" />
    <input v-model="form.dataType" class="input" placeholder="Data type (CSV, Images, API…)" />

    <div class="flex gap-4">
      <input
          v-model.number="form.coverage"
          type="number"
          min="1"
          max="100"
          class="input"
          placeholder="Coverage %"
      />
      <input
          v-model.number="form.price"
          type="number"
          class="input"
          placeholder="Requested price ($)"
      />
    </div>

    <textarea
        v-model="form.message"
        class="input"
        placeholder="Optional message"
    />

    <button class="bg-black text-white px-4 py-2 rounded">
      Submit
    </button>
  </form>
</template>