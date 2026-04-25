<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api/client'

const PHASES = [
  { to: '/router',   label: '路由層',      sub: 'Layer 0 · Router',   color: '#f5c518',
    path: 'M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 0-2-2V9m0 0h18' },
  { to: '/memory',   label: '日常記憶層',  sub: 'Layer 1 · Memory',   color: '#40c4ff',
    path: 'M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4' },
  { to: '/teachers', label: '師父管理',    sub: 'Layer 2 · Chamber',  color: '#c084fc',
    path: 'M12 14l9-5-9-5-9 5 9 5z M12 14l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z' },
  { to: '/pipeline', label: 'Fine-tuning', sub: 'Layer 3 · Pipeline', color: '#ffab40',
    path: 'M13 10V3L4 14h7v7l9-11h-7z' },
]

// System status：偵測 backend 是否在線（失敗不阻塞 UI）
const systemUp = ref(false)
onMounted(async () => {
  try {
    await api.get('/router/status')
    systemUp.value = true
  } catch {
    systemUp.value = false
  }
})
</script>

<template>
  <aside
    class="shrink-0 flex flex-col overflow-hidden h-screen"
    style="width:220px; background:#0a0c0f; border-right:1px solid #21262f"
  >
    <!-- Logo -->
    <div
      class="flex items-center"
      style="padding:18px 16px 14px; border-bottom:1px solid #191d24; gap:10px"
    >
      <div
        class="shrink-0 rounded-md flex items-center justify-center font-display font-bold"
        style="width:44px; height:44px; background:linear-gradient(135deg,#dce6ee,#9aafc4); color:#111318; font-size:18px"
      >
        S
      </div>
      <div>
        <div
          class="font-display font-bold"
          style="font-size:15px; background:linear-gradient(90deg,#dce6ee,#9aafc4); -webkit-background-clip:text; -webkit-text-fill-color:transparent"
        >
          Shiba
        </div>
        <div class="font-mono" style="font-size:10px; color:#505c6e">
          v0.9.0 · fine-tuning
        </div>
      </div>
    </div>

    <!-- Nav -->
    <nav class="flex-1 flex flex-col" style="padding:12px 8px; gap:2px">
      <router-link
        v-for="p in PHASES"
        :key="p.to"
        :to="p.to"
        custom
        v-slot="{ isActive, navigate }"
      >
        <button
          @click="navigate"
          class="flex items-center border-0 cursor-pointer text-left transition-all duration-150"
          style="padding:10px; border-radius:10px; gap:10px"
          :style="{
            background: isActive ? '#191d24' : 'transparent',
            boxShadow:  isActive ? '0 2px 8px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.04)' : 'none',
            borderLeft: isActive ? `3px solid ${p.color}` : '3px solid transparent',
          }"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
               :stroke="isActive ? p.color : '#505c6e'" stroke-width="1.8"
               stroke-linecap="round" stroke-linejoin="round">
            <path :d="p.path" />
          </svg>
          <div>
            <div
              class="font-body"
              style="font-size:13px; letter-spacing:-0.01em"
              :style="{
                fontWeight: isActive ? 600 : 400,
                color: isActive ? '#edf0f4' : '#8a97a8',
              }"
            >
              {{ p.label }}
            </div>
            <div class="font-mono" style="font-size:10px; color:#505c6e; margin-top:1px">
              {{ p.sub }}
            </div>
          </div>
        </button>
      </router-link>
    </nav>

    <!-- System status -->
    <div style="padding:14px 16px; border-top:1px solid #191d24">
      <div
        class="font-mono uppercase"
        style="font-size:10px; color:#505c6e; margin-bottom:8px; letter-spacing:0.06em"
      >
        System
      </div>
      <div class="flex items-center justify-between" style="margin-bottom:5px">
        <span class="font-mono" style="font-size:11px; color:#505c6e">Backend</span>
        <span
          class="font-mono flex items-center"
          style="font-size:11px; gap:4px"
          :style="{ color: systemUp ? '#00e676' : '#ff5252' }"
        >
          <span
            class="inline-block rounded-full"
            style="width:5px; height:5px"
            :style="{ background: systemUp ? '#00e676' : '#ff5252' }"
          />
          {{ systemUp ? '連線中' : '離線' }}
        </span>
      </div>
    </div>
  </aside>
</template>
