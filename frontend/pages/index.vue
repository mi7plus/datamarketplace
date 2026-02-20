<script setup lang="ts">
import PageWrapper from '~/components/layout/PageWrapper.vue'
</script>

<template>
  <PageWrapper class="flex flex-col justify-center items-center">
    <h1 class="text-4xl font-bold mb-4 text-center">
      Open Data for Everyone
    </h1>
    <p class="text-gray-600 mb-8 text-center">
      Request, collect, and exchange data for AI & analytics.
    </p>
    <div class="flex justify-center gap-4">
      <NuxtLink
          to="/requests/create"
          class="bg-black text-white px-6 py-3 rounded"
      >
        Post a Data Request
      </NuxtLink>
      <NuxtLink
          to="/requests"
          class="border px-6 py-3 rounded"
      >
        Browse Requests
      </NuxtLink>
    </div>
  </PageWrapper>
</template>