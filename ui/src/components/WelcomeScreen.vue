<script setup lang="ts">
import InputBox from './InputBox.vue'
const hints = [
  '5 天大阪亲子游',
  '3 天北京文化深度',
  '7 天东京美食之旅',
  '5 天三亚海岛度假',
]

defineProps<{ onPick?: (s: string) => void }>()
</script>

<template>
  <div class="welcome">
    <h1>
      <span class="title-grad">智能旅行助手</span>
    </h1>
    <p>
      告诉我目的地、人数和天数，我会一次性帮你查天气、机票、酒店和景点，<br />
      生成可下载的行程方案，并支持后续多轮调整。
    </p>
    <div class="hints">
      <button class="hint-chip" v-for="h in hints" :key="h" @click="onPick && onPick(h)">{{ h }}</button>
    </div>
  </div>
  <InputBox :show-form="true" placeholder="描述你的诉求，例如：5 天大阪亲子游，预算每人 8000 元" />
</template>
