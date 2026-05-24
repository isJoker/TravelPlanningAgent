<script setup lang="ts">
import type { Message } from '@/types/chat'
defineProps<{ msg: Message }>()
</script>

<template>
  <div class="msg-user">{{ msg.content }}</div>
</template>
