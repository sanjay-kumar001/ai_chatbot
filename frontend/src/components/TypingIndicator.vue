<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->
<template>
  <div class="flex items-center gap-3">
    <img
      :src="logoSvg"
      alt="AI"
      class="w-6 h-6 rounded-full flex-shrink-0"
    />
    <div class="flex items-center gap-2">
      <div class="flex gap-1">
        <div class="w-2 h-2 bg-blue-600 rounded-full animate-bounce" style="animation-delay: 0ms"></div>
        <div class="w-2 h-2 bg-blue-600 rounded-full animate-bounce" style="animation-delay: 150ms"></div>
        <div class="w-2 h-2 bg-blue-600 rounded-full animate-bounce" style="animation-delay: 300ms"></div>
      </div>
      <span class="text-gray-600 dark:text-gray-400 text-base">{{ processStep || 'AI is thinking...' }}</span>
    </div>
  </div>
</template>

<script setup>
import { inject } from 'vue'

const logoSvg = inject('logoSvg')

defineProps({
  processStep: {
    type: String,
    default: '',
  },
})
</script>
