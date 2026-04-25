<script setup lang="ts">
interface Props {
  open: boolean
  title: string
}
defineProps<Props>()
const emit = defineEmits<{ (e: 'close'): void }>()
</script>

<template>
  <div
    class="fixed top-0 right-0 bottom-0 overflow-hidden flex flex-col z-[100] transition-[width] duration-200"
    style="background:#191d24; border-left:1px solid #21262f; transition-timing-function: cubic-bezier(0.4,0,0.2,1)"
    :style="{
      width: open ? '380px' : '0',
      boxShadow: open ? '-8px 0 32px rgba(0,0,0,0.7)' : 'none',
    }"
  >
    <template v-if="open">
      <div
        class="flex items-center justify-between"
        style="padding:14px 18px; border-bottom:1px solid #21262f; background:#111318"
      >
        <span class="font-display font-semibold" style="font-size:14px; color:#edf0f4">
          {{ title }}
        </span>
        <button
          @click="emit('close')"
          class="bg-transparent border-0 cursor-pointer"
          style="color:#505c6e; font-size:20px; line-height:1; padding:2px 6px; border-radius:4px"
        >
          ×
        </button>
      </div>
      <div class="flex-1 overflow-auto" style="padding:18px">
        <slot />
      </div>
    </template>
  </div>
</template>
