<script setup lang="ts">
import PageWrapper from '~/components/layout/PageWrapper.vue'
</script>

<template>
  <PageWrapper class="max-w-4xl mx-auto px-6 py-12">
    <h1 class="font-wordmark text-3xl font-bold mb-6 text-ink">About Rowbound</h1>
    <p class="text-gray-700 mb-4">
      Rowbound is a data clearing house: get exactly the data you need — buy it from a
      catalog, request it from suppliers, or commission its collection — and pay only for
      the records that actually match what you asked for.
    </p>
    <p class="text-gray-700 mb-4">
      Every transaction runs through one funded, escrowed settlement engine. Records are
      priced per unit, deduplicated across sources so you never pay twice for the same row,
      and delivered only after escrow is in place — with the licence and provenance of each
      record travelling with it.
    </p>
    <p class="text-gray-700">
      Three ways to get data, one settlement engine — rows bound to a single spine.
    </p>
  </PageWrapper>
</template>