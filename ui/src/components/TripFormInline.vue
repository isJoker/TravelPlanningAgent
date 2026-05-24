<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { TripRequest } from '@/types/trip'

const props = defineProps<{ modelValue: TripRequest }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: TripRequest): void }>()

const form = reactive<TripRequest>({ ...props.modelValue })

watch(form, (v) => emit('update:modelValue', { ...v }), { deep: true })
watch(
  () => props.modelValue,
  (v) => Object.assign(form, v),
  { deep: true }
)
</script>

<template>
  <div class="form-inline">
    <label class="field">
      目的地 *
      <input v-model="form.destination" placeholder="如：大阪" />
    </label>
    <label class="field">
      出发地
      <input v-model="form.departure" placeholder="如：上海" />
    </label>
    <label class="field">
      天数 *
      <input v-model.number="form.days_num" type="number" min="1" max="30" />
    </label>
    <label class="field">
      人数 *
      <input v-model.number="form.people_num" type="number" min="1" max="20" />
    </label>
    <label class="field">
      出发日期
      <input v-model="form.start_date" type="date" />
    </label>
    <label class="field">
      主题
      <select v-model="form.travel_theme">
        <option value="">通用</option>
        <option value="亲子">亲子</option>
        <option value="蜜月">蜜月</option>
        <option value="美食">美食</option>
        <option value="户外">户外</option>
        <option value="文化">文化</option>
      </select>
    </label>
  </div>
</template>
