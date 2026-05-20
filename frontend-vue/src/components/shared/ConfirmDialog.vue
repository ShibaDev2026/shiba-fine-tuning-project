<script setup lang="ts">
import Modal from './Modal.vue'

interface Props {
  open: boolean
  title?: string
  message?: string
  confirmLabel?: string
  cancelLabel?: string
  confirmVariant?: 'danger' | 'primary'
}
const props = withDefaults(defineProps<Props>(), {
  title: '確認',
  message: '',
  confirmLabel: '確認',
  cancelLabel: '取消',
  confirmVariant: 'danger',
})
const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

const CONFIRM_STYLE: Record<string, Record<string, string>> = {
  danger:  { background: '#2c0000', color: '#ff5252' },
  primary: { background: 'linear-gradient(135deg,#dce6ee,#9aafc4)', color: '#111318' },
}
</script>

<template>
  <Modal :open="open" :title="title" width="360px" @close="$emit('cancel')">
    <div class="flex flex-col" style="gap:18px">
      <p v-if="message" class="font-body" style="font-size:13px; color:#8a97a8; line-height:1.6; margin:0">
        {{ message }}
      </p>
      <div class="flex" style="gap:8px; justify-content:flex-end">
        <button
          class="font-body border-0 cursor-pointer"
          style="background:#21262f; color:#edf0f4; padding:6px 16px; border-radius:8px; font-size:12px"
          @click="$emit('cancel')"
        >{{ cancelLabel }}</button>
        <button
          class="font-body border-0 cursor-pointer font-semibold"
          :style="{ ...CONFIRM_STYLE[confirmVariant], padding:'6px 16px', borderRadius:'8px', fontSize:'12px' }"
          @click="$emit('confirm')"
        >{{ confirmLabel }}</button>
      </div>
    </div>
  </Modal>
</template>
