<script setup lang="ts">
interface Props {
  title: string
  sub?: string
  accent?: string  // 左側裝飾條顏色（HEX）
}
defineProps<Props>()
</script>

<template>
  <div class="flex items-start justify-between" style="margin-bottom:20px">
    <div class="flex flex-col" style="gap:3px">
      <div class="flex items-center" style="gap:10px">
        <div
          v-if="accent"
          style="width:3px; height:22px; border-radius:2px"
          :style="{ background: accent }"
        />
        <h2
          class="font-display font-bold m-0"
          style="font-size:20px; color:#edf0f4; letter-spacing:-0.01em"
        >
          {{ title }}
        </h2>
      </div>
      <span
        v-if="sub"
        style="font-size:12px; color:#505c6e"
        :style="{ marginLeft: accent ? '13px' : '0' }"
      >
        {{ sub }}
      </span>
    </div>
    <div class="flex" style="gap:6px">
      <slot name="actions" />
    </div>
  </div>
</template>
