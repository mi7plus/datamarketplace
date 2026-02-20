<script setup lang="ts">
import RequestCard from '~/components/requests/RequestCard.vue'
import { useRequests } from '~/composables/useRequests'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import BackButton from '~/components/BackButton.vue'

const { requests } = useRequests()
</script>

<template>
  <PageWrapper>
    <BackButton fallback="/requests" />
    <h1 class="text-2xl font-bold mb-6">
      Browse Data Requests
    </h1>

    <div class="grid gap-4">
      <RequestCard
          v-for="req in requests"
          :key="req.id"
          v-bind="req"
      />
    </div>
  </PageWrapper>
</template>