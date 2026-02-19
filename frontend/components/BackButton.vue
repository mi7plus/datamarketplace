<script setup lang="ts">
import { useRouter } from 'vue-router'

const props = defineProps<{
  fallback?: string
}>()

const router = useRouter()

const goBack = () => {
  if (window.history.length > 1) {
    router.back()
  } else if (props.fallback) {
    router.push(props.fallback)
  } else {
    router.push('/')
  }
}
</script>

<template>
  <button
      @click="goBack"
      class="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-black mb-4"
  >
    ← Back
  </button>
</template>