<script setup lang="ts">
import { computed } from 'vue'

type Variant = 'primary' | 'ghost' | 'danger' | 'cyan'
interface Props {
  variant?: Variant
  loading?: boolean
}
const props = withDefaults(defineProps<Props>(), { variant: 'ghost', loading: false })

const VARIANTS: Record<Variant, Record<string, string>> = {
  primary: {
    background: 'linear-gradient(135deg,#dce6ee 0%,#9aafc4 40%,#d0dce8 100%)',
    color: '#111318',
    fontWeight: '600',
    boxShadow: '0 1px 3px rgba(0,0,0,0.4),inset 0 1px 0 rgba(255,255,255,0.08)',
  },
  ghost:  { background: '#21262f', color: '#edf0f4' },
  danger: { background: '#2c0000', color: '#ff5252' },
  cyan:   { background: '#033848', color: '#06c8e8', border: '1px solid #06c8e880' },
}

const style = computed(() => ({
  ...(VARIANTS[props.variant] ?? VARIANTS.ghost),
  cursor: props.loading ? 'not-allowed' : 'pointer',
  opacity: props.loading ? 0.6 : 1,
}))
</script>

<template>
  <button
    class="inline-flex items-center font-body border-0 transition-all duration-100"
    style="gap:6px; font-size:12px; font-weight:500; padding:5px 12px; border-radius:8px"
    :style="style"
    :disabled="loading"
  >
    <span
      v-if="loading"
      style="display:inline-block; width:11px; height:11px; border:2px solid currentColor; border-top-color:transparent; border-radius:50%; animation:btn-spin 0.6s linear infinite; flex-shrink:0"
    />
    <slot />
  </button>
</template>

<style>
@keyframes btn-spin { to { transform: rotate(360deg); } }
</style>
