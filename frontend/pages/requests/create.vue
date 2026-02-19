<script setup>
import RequestForm from '~/components/requests/RequestForm.vue'
import BackButton from '~/components/BackButton.vue'
import PageWrapper from '~/components/layout/PageWrapper.vue'
</script>

<template>
  <PageWrapper>
    <BackButton fallback="/requests" />
    <h1 class="text-2xl font-bold mb-6">
      Create Data Request
    </h1>

    <RequestForm />
  </PageWrapper>
</template>