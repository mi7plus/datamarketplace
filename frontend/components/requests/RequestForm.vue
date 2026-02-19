<script setup lang="ts">
import { ref } from 'vue'

const form = ref({
  title: '',
  description: '',
  dataTypes: '',
  quantity: '',
  budget: '',
})
</script>

<template>
  <form class="space-y-4 max-w-xl">
    <input v-model="form.title" placeholder="Title" class="input" />
    <textarea v-model="form.description" placeholder="Description" class="input" />
    <input v-model="form.dataTypes" placeholder="Data types (CSV, Images, Logs...)" class="input" />
    <input v-model="form.quantity" placeholder="Quantity needed" class="input" />
    <input v-model="form.budget" placeholder="Total budget ($)" class="input" />
    <button class="bg-black text-white px-4 py-2 rounded">
      Create Request
    </button>
  </form>
</template>