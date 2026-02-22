<script setup lang="ts">
import PageWrapper from '~/components/layout/PageWrapper.vue'
import BackButton from '~/components/BackButton.vue'
definePageMeta({
  middleware: 'auth'
})
</script>
<template>
  <PageWrapper>
    <BackButton fallback="/submissions" />
    <h1 class="text-2xl font-bold mb-4">
      My Submissions
    </h1>

    <p class="text-gray-500">
      This page will show data you’ve submitted to requests.
    </p>
  </PageWrapper>
</template>