<script setup>
// Posting a data request requires an account — redirect to /login if signed out.
definePageMeta({ middleware: 'auth' })
import RequestForm from '~/components/requests/RequestForm.vue'
import BackButton from '~/components/BackButton.vue'
import PageWrapper from '~/components/layout/PageWrapper.vue'
</script>

<template>
  <PageWrapper>
    <BackButton fallback="/requests" />
    <h1 class="text-2xl font-bold text-ink mb-1">
      Create Data Request
    </h1>
    <p class="text-sm text-muted mb-6">
      New to this? Read
      <NuxtLink to="/guides/how-to-write-a-good-data-request" class="text-accent-deep hover:underline">how to write a good data request</NuxtLink>.
    </p>

    <RequestForm />
  </PageWrapper>
</template>