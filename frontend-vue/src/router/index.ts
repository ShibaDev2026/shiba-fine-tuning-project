import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/',          redirect: '/router' },
    { path: '/router',    component: () => import('../views/PhaseRouter.vue') },
    { path: '/memory',    component: () => import('../views/PhaseMemory.vue') },
    { path: '/teachers',  component: () => import('../views/PhaseTeachers.vue') },
    { path: '/pipeline',  component: () => import('../views/PhasePipeline.vue') },
  ],
})

export default router
