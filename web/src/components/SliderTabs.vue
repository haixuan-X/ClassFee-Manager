<script setup lang="ts">
import { computed } from 'vue'

/**
 * 顶部滑动切换器（仪表盘在「班级账目总览」和「学生情况总览」之间推拉）。
 *
 * 为什么自己写而不用 el-tabs/el-radio-group：
 * - el-radio-button 的圆角/高亮是**按按钮宽度等分**的，两段文案长短不一时
 *   滑块会和高亮块对不上（这里「班级账目总览」7 字、「学生情况总览」6 字）。
 * - 滑块用 `left` + `width` 由**文字实际宽度**驱动，永远和内容对齐。
 *
 * 无障碍：这是个 tablist 的语义（两组互斥视图），所以用 `role="tablist"` +
 * `aria-selected`；键盘交给两个 `role="tab"` 按钮自己处理（原生 button 可 Tab、
 * 可回车/空格触发），**不额外实现方向键**——加了就得配套 roving tabindex，
 * 做一半反而更糟。
 */
const props = defineProps<{
  modelValue: string
  items: { value: string; label: string }[]
}>()

const emit = defineEmits<{ 'update:modelValue': [string] }>()

/** 当前项在整条里的横向偏移与宽度（百分比），滑块靠这两个值滑动 */
const thumbStyle = computed(() => {
  const i = props.items.findIndex((it) => it.value === props.modelValue)
  if (i < 0 || props.items.length === 0) return { left: '0%', width: '0%' }
  const w = 100 / props.items.length
  return { left: `${i * w}%`, width: `${w}%` }
})
</script>

<template>
  <div class="slider-tabs" role="tablist" aria-label="总览切换">
    <span class="thumb" :style="thumbStyle" aria-hidden="true" />
    <button
      v-for="it in props.items"
      :key="it.value"
      type="button"
      role="tab"
      class="tab"
      :class="{ 'is-active': it.value === props.modelValue }"
      :aria-selected="it.value === props.modelValue"
      @click="emit('update:modelValue', it.value)"
    >
      {{ it.label }}
    </button>
  </div>
</template>

<style scoped>
.slider-tabs {
  position: relative;
  display: inline-flex;
  padding: 3px;
  border-radius: 999px;
  background: var(--color-muted);
  /* 两个 tab 等宽，但滑块按同样比例定位，两边不会错位 */
  isolation: isolate;
}

.thumb {
  position: absolute;
  top: 3px;
  bottom: 3px;
  border-radius: 999px;
  background: var(--color-surface, #fff);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.16);
  transition: left 0.22s cubic-bezier(0.4, 0, 0.2, 1),
    width 0.22s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 0;
}

.tab {
  position: relative;
  z-index: 1;
  border: 0;
  background: none;
  padding: 8px 22px;
  min-height: 40px;
  font: inherit;
  font-size: 14px;
  color: var(--color-muted-fg);
  cursor: pointer;
  border-radius: 999px;
  /* 两段文案等宽，按钮宽度才和滑块对齐 */
  min-width: 140px;
  white-space: nowrap;
  transition: color 0.18s ease;
}

.tab.is-active {
  color: var(--color-foreground);
  font-weight: 600;
}

.tab:hover:not(.is-active) {
  color: var(--color-foreground);
}

.tab:focus-visible {
  outline: 2px solid var(--color-accent-text);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .thumb {
    transition: none;
  }
}

@media (max-width: 480px) {
  .slider-tabs {
    display: flex;
  }

  .tab {
    flex: 1;
    min-width: 0;
    padding: 8px 10px;
  }
}
</style>