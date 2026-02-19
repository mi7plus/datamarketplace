<script setup lang="ts">
defineProps<{
  id: string
  title: string
  description: string
  budget: number
  coverage: number
}>()
</script>

<template>
  <NuxtLink
      :to="`/requests/${id}`"
      class="block border rounded-lg p-4 bg-white hover:shadow transition"
  >
    <div class="flex justify-between items-start">
      <div>
        <h3 class="text-lg font-semibold">
          {{ title }}
        </h3>
        <p class="text-gray-600 text-sm mt-1">
          {{ description }}
        </p>
      </div>

      <div class="text-right">
        <div class="font-bold">
          ${{ budget }}
        </div>
        <div class="text-xs text-gray-500">
          {{ coverage }}% filled
        </div>
      </div>
    </div>

    <div class="mt-3 h-2 bg-gray-200 rounded">
      <div
          class="h-2 bg-green-500 rounded"
          :style="{ width: coverage + '%' }"
      />
    </div>
  </NuxtLink>
</template>