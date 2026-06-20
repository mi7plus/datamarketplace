<script setup>
// Session rehydration is handled by plugins/auth.client.ts (re-mints the access
// token from the httpOnly refresh cookie). No localStorage token here by design.
</script>
<template>
  <div class="min-h-screen flex flex-col bg-surface">
    <!-- Header -->
    <AppHeader />

    <!-- Main content -->
    <main class="flex-1 max-w-6xl mx-auto p-6 w-full">
      <NuxtPage />
    </main>

    <!-- Footer -->
    <AppFooter />
  </div>
</template>