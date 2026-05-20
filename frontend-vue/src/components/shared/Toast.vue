<script setup lang="ts">
import { useToastStore } from '../../stores/toast'

const store = useToastStore()

const TYPE_STYLE: Record<string, Record<string, string>> = {
  success: { background: '#0a2218', color: '#00e676', border: '1px solid #00e67640' },
  error:   { background: '#2c0000', color: '#ff5252', border: '1px solid #ff525240' },
  info:    { background: '#033848', color: '#06c8e8', border: '1px solid #06c8e840' },
}
</script>

<template>
  <div
    class="fixed flex flex-col"
    style="top:20px; right:20px; z-index:2000; gap:8px; pointer-events:none; min-width:220px; max-width:320px"
  >
    <TransitionGroup name="toast">
      <div
        v-for="t in store.toasts"
        :key="t.id"
        class="font-mono"
        :style="{
          ...TYPE_STYLE[t.type],
          padding: '9px 14px',
          borderRadius: '8px',
          fontSize: '12px',
          lineHeight: '1.5',
          pointerEvents: 'auto',
          boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
        }"
        @click="store.remove(t.id)"
      >
        {{ t.message }}
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active { transition: all 200ms ease; }
.toast-leave-active { transition: all 180ms ease; }
.toast-enter-from   { opacity: 0; transform: translateX(20px); }
.toast-leave-to     { opacity: 0; transform: translateX(20px); }
</style>
