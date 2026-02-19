<script setup lang="ts">
// No props needed for now, just wraps page content
</script>

<template>
  <div class="min-h-[calc(100vh-4rem-16rem)] flex flex-col overflow-auto">
    <!-- Use default slot for page content -->
    <slot />
  </div>
</template>

<style>
/* Optional: adjust header/footer heights if they differ */
</style>