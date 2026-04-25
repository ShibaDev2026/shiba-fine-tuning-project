<script setup lang="ts" generic="T extends Record<string, any>">
// 通用表格：columns 支援 render slot-style（透過 columnRenders slot），mono 欄位使用等寬字體
export interface Column {
  key: string
  label: string
  mono?: boolean
}

interface Props {
  columns: Column[]
  rows: T[]
  selectedId?: string | number | null
  keyField?: string
}
const props = withDefaults(defineProps<Props>(), { keyField: 'id', selectedId: null })

const emit = defineEmits<{ (e: 'select', row: T): void }>()

function rowKey(row: T): string | number {
  return row[props.keyField] as string | number
}
function isSelected(row: T): boolean {
  return props.selectedId != null && rowKey(row) === props.selectedId
}
</script>

<template>
  <div class="overflow-x-auto">
    <table class="w-full border-collapse text-sm">
      <thead>
        <tr>
          <th
            v-for="c in columns"
            :key="c.key"
            class="text-left px-3 py-2 font-mono uppercase whitespace-nowrap font-medium"
            style="color:#505c6e; font-size:11px; border-bottom:1px solid #2c333e; letter-spacing:0.05em"
          >
            {{ c.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="rowKey(row)"
          @click="emit('select', row)"
          class="cursor-pointer transition-colors"
          :style="{
            background: isSelected(row) ? '#033848' : 'transparent',
            borderLeft: isSelected(row) ? '2px solid #06c8e8' : '2px solid transparent',
          }"
        >
          <td
            v-for="c in columns"
            :key="c.key"
            class="px-3 whitespace-nowrap"
            :style="{
              padding: '9px 12px',
              borderBottom: '1px solid #191d24',
              color: isSelected(row) ? '#edf0f4' : '#8a97a8',
              fontFamily: c.mono ? 'var(--font-mono, monospace)' : 'inherit',
              fontSize: c.mono ? '11px' : '12px',
            }"
          >
            <slot :name="`cell-${c.key}`" :row="row" :value="row[c.key]">
              {{ row[c.key] ?? '—' }}
            </slot>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
