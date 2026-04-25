<script setup lang="ts">
import { RouterView } from 'vue-router'
import Sidebar from './components/Sidebar.vue'
</script>

<template>
  <div class="flex h-screen overflow-hidden" style="background:#111318">
    <Sidebar />
    <main class="flex-1 overflow-auto" style="padding:24px 28px; min-width:0">
      <div :key="$route.path" class="phase-content">
        <RouterView />
      </div>
    </main>
  </div>
</template>

<style>
@keyframes fade-in {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}
.phase-content { animation: fade-in 220ms ease; }
</style>
