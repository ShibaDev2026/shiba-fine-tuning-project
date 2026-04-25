<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { Chart, registerables } from 'chart.js'

Chart.register(...registerables)

// trend 格式：{ '2026-04-18': { git_ops: 3, code_gen: 2, ... }, ... }
interface Props {
  trend: Record<string, Record<string, number>> | null | undefined
}
const props = defineProps<Props>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
let chart: Chart | null = null

const ET_DESC: Record<string, string> = {
  git_ops:         '#f5c518',
  terminal_ops:    '#00e676',
  code_gen:        '#40c4ff',
  debugging:       '#ff5252',
  architecture:    '#c084fc',
  knowledge_qa:    '#00bfa5',
  fine_tuning_ops: '#ffab40',
}

function render() {
  if (!canvasRef.value) return
  const t = props.trend
  if (!t || Object.keys(t).length === 0) {
    if (chart) { chart.destroy(); chart = null }
    return
  }
  const days = Object.keys(t).sort()
  const labels = days.map(d => d.slice(5))
  const datasets = Object.entries(ET_DESC).map(([et, color]) => ({
    label: et,
    data: days.map(day => t[day]?.[et] ?? 0),
    backgroundColor: color,
    stack: 's',
  }))
  if (chart) chart.destroy()
  chart = new Chart(canvasRef.value.getContext('2d')!, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#505c6e', font: { family: 'IBM Plex Mono', size: 10 } }, grid: { color: '#1a2030' } },
        y: { ticks: { color: '#505c6e', font: { family: 'IBM Plex Mono', size: 10 } }, grid: { color: '#1a2030' } },
      },
      animation: { duration: 600 },
    },
  })
}

onMounted(() => nextTick(render))
watch(() => props.trend, () => nextTick(render))
onBeforeUnmount(() => { if (chart) chart.destroy() })
</script>

<template>
  <canvas ref="canvasRef" width="500" height="120" />
</template>
