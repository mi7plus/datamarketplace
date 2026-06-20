<script setup lang="ts">
// No script needed for static footer
</script>

<template>
  <footer class="bg-ink mt-12">
    <div class="max-w-6xl mx-auto px-6 py-8 flex flex-col md:flex-row justify-between items-center gap-4 text-sm text-slate-300">

      <!-- Left: reversed lockup + tagline -->
      <div class="flex flex-col items-center md:items-start gap-1">
        <img src="/brand/Rowbound_logo_reversed.svg" alt="Rowbound" class="h-7" />
        <span class="text-slate-400 text-xs">The data clearing house · &copy; {{ new Date().getFullYear() }} Rowbound</span>
      </div>

      <!-- Right / Links -->
      <div class="flex gap-6">
        <NuxtLink to="/about" class="hover:text-accent transition-colors">About</NuxtLink>
        <NuxtLink to="/terms" class="hover:text-accent transition-colors">Terms</NuxtLink>
        <NuxtLink to="/privacy" class="hover:text-accent transition-colors">Privacy</NuxtLink>
        <a href="mailto:contact@rowbound.io" class="hover:text-accent transition-colors">Contact</a>
      </div>

    </div>
  </footer>
</template>