import { createRouter, createWebHistory } from 'vue-router'
import EnhancePage from './pages/EnhancePage.vue'
import KleinPage from './pages/KleinPage.vue'
import AnglePage from './pages/AnglePage.vue'
import ZimagePage from './pages/ZimagePage.vue'

export default createRouter({
  history: createWebHistory('/static/'),
  routes: [
    { path: '/enhance', component: EnhancePage },
    { path: '/klein', component: KleinPage },
    { path: '/angle', component: AnglePage },
    { path: '/zimage', component: ZimagePage },
  ]
})