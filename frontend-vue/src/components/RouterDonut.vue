<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { Chart, registerables } from 'chart.js'

Chart.register(...registerables)

// localPct：Local 路由佔比（0–100）
interface Props {
  localPct: number
}
const props = defineProps<Props>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
let chart: Chart | null = null

function render() {
  if (!canvasRef.value) return
  if (chart) chart.destroy()
  chart = new Chart(canvasRef.value.getContext('2d')!, {
    type: 'doughnut',
    data: {
      labels: ['local', 'claude'],
      datasets: [{
        data: [props.localPct, 100 - props.localPct],
        backgroundColor: ['#f5c518', '#c084fc'],
        borderWidth: 0,
        hoverOffset: 4,
      }],
    },
    options: {
      cutout: '72%',
      responsive: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      animation: { duration: 600 },
    },
  })
}

onMounted(() => nextTick(render))
watch(() => props.localPct, () => nextTick(render))
onBeforeUnmount(() => { if (chart) chart.destroy() })
</script>

<template>
  <canvas ref="canvasRef" width="130" height="130" />
</template>
