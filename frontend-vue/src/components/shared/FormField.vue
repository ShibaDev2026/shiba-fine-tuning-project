<script setup lang="ts">
interface Props {
  label: string
  error?: string
  hint?: string
  required?: boolean
}
withDefaults(defineProps<Props>(), { error: '', hint: '', required: false })
</script>

<template>
  <div class="flex flex-col" style="gap:5px">
    <label class="font-mono" style="font-size:11px; color:#8a97a8">
      {{ label }}<span v-if="required" style="color:#ff5252; margin-left:3px">*</span>
    </label>
    <slot />
    <span v-if="hint && !error" class="font-mono" style="font-size:10px; color:#505c6e">{{ hint }}</span>
    <span v-if="error" class="font-mono" style="font-size:10px; color:#ff5252">{{ error }}</span>
  </div>
</template>
