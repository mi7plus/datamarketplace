<script setup lang="ts">
// No script needed for static footer
</script>

<template>
  <footer class="bg-white border-t mt-12">
    <div class="max-w-6xl mx-auto px-6 py-6 flex flex-col md:flex-row justify-between items-center text-sm text-gray-500">

      <!-- Left -->
      <div class="mb-4 md:mb-0">
        &copy; {{ new Date().getFullYear() }} Data Exchange. All rights reserved.
      </div>

      <!-- Right / Links -->
      <div class="flex gap-6">
        <NuxtLink to="/about" class="hover:text-black">About</NuxtLink>
        <NuxtLink to="/terms" class="hover:text-black">Terms</NuxtLink>
        <NuxtLink to="/privacy" class="hover:text-black">Privacy</NuxtLink>
        <a href="mailto:contact@dataexchange.com" class="hover:text-black">Contact</a>
      </div>

    </div>
  </footer>
</template>