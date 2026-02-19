<script setup lang="ts">
import type { Submission } from '~/types/submission'

defineProps<{
  submission: Submission
}>()
</script>

<template>
  <div class="border rounded p-4 bg-gray-50">
    <div class="flex justify-between">
      <div>
        <h4 class="font-semibold">{{ submission.providerName }}</h4>
        <p class="text-sm text-gray-600">
          {{ submission.dataType }} • {{ submission.coverage }}% coverage
        </p>
      </div>

      <div class="font-bold">
        ${{ submission.price }}
      </div>
    </div>

    <p v-if="submission.message" class="text-sm mt-2 text-gray-700">
      "{{ submission.message }}"
    </p>

    <div class="mt-3 flex gap-2">
      <button class="px-3 py-1 bg-green-600 text-white rounded text-sm">
        Accept
      </button>
      <button class="px-3 py-1 bg-red-500 text-white rounded text-sm">
        Reject
      </button>
    </div>
  </div>
</template>