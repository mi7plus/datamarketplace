<script setup lang="ts">
import PageWrapper from '~/components/layout/PageWrapper.vue'
</script>

<template>
  <PageWrapper class="flex flex-col justify-center items-center">
    <img src="/brand/Rowbound_icon_tile.svg" alt="Rowbound" class="h-16 w-16 mb-6" />
    <h1 class="font-wordmark text-4xl md:text-5xl font-bold mb-4 text-center text-ink">
      Get exactly the data you need
    </h1>
    <p class="text-muted mb-2 text-center text-lg max-w-2xl">
      Buy it, request it, or collect it — and pay only for matching records.
    </p>
    <p class="text-surface-label mb-10 text-center text-sm tracking-wide uppercase">
      The data clearing house
    </p>

    <div class="flex justify-center gap-4">
      <NuxtLink
          to="/requests/create"
          class="bg-ink text-white px-6 py-3 rounded-lg hover:bg-ink/90 transition-colors"
      >
        Post a Data Request
      </NuxtLink>
      <NuxtLink
          to="/requests"
          class="border border-surface-border text-ink px-6 py-3 rounded-lg hover:border-accent transition-colors"
      >
        Browse Requests
      </NuxtLink>
    </div>
  </PageWrapper>
</template>