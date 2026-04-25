<script setup lang="ts">
interface Props {
  label: string
  value: string | number
  sub?: string
  color?: string  // 主數字色
}
withDefaults(defineProps<Props>(), { color: '#edf0f4' })
</script>

<template>
  <div
    class="flex flex-col"
    style="
      background:#191d24; border-radius:12px;
      box-shadow:0 2px 8px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.04);
      padding:14px 18px; gap:6px;
    "
  >
    <div
      class="font-mono uppercase"
      style="font-size:11px; color:#505c6e; letter-spacing:0.05em"
    >
      {{ label }}
    </div>
    <div
      class="font-display font-bold"
      style="font-size:26px; line-height:1; letter-spacing:-0.02em"
      :style="{ color }"
    >
      {{ value }}
    </div>
    <div
      v-if="sub"
      class="font-mono"
      style="font-size:11px; color:#505c6e"
    >
      {{ sub }}
    </div>
  </div>
</template>
