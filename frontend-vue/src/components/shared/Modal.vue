<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

interface Props {
  open: boolean
  title?: string
  width?: string
}
const props = withDefaults(defineProps<Props>(), { title: '', width: '480px' })
const emit = defineEmits<{ (e: 'close'): void }>()

function onKey(ev: KeyboardEvent) {
  if (props.open && ev.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="open"
        class="fixed inset-0 flex items-center justify-center"
        style="z-index:1000; background:rgba(0,0,0,0.6); padding:24px"
        @click.self="$emit('close')"
      >
        <div
          class="flex flex-col"
          :style="{
            width,
            maxWidth: '100%',
            maxHeight: '90vh',
            background: '#191d24',
            borderRadius: '14px',
            boxShadow: '0 8px 32px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.06)',
            overflow: 'hidden',
          }"
        >
          <!-- Header -->
          <div
            v-if="title"
            class="flex items-center justify-between shrink-0"
            style="padding:14px 18px; border-bottom:1px solid #21262f"
          >
            <span class="font-display font-semibold" style="font-size:14px; color:#edf0f4">{{ title }}</span>
            <button
              class="border-0 cursor-pointer flex items-center justify-center"
              style="background:transparent; color:#505c6e; font-size:18px; line-height:1; padding:2px 6px"
              @click="$emit('close')"
            >×</button>
          </div>
          <!-- Body -->
          <div class="flex-1 overflow-auto" style="padding:18px">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-enter-active, .modal-leave-active { transition: opacity 150ms ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
</style>
