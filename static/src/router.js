import { createRouter, createWebHistory } from 'vue-router'
import EnhancePage from './pages/EnhancePage.vue'
import KleinPage from './pages/KleinPage.vue'
import AnglePage from './pages/AnglePage.vue'
import ZimagePage from './pages/ZimagePage.vue'
import ApiSettingsPage from './pages/ApiSettingsPage.vue'
import ComfyuiSettingsPage from './pages/ComfyuiSettingsPage.vue'
import CanvasListPage from './pages/CanvasListPage.vue'
import AssetManagerPage from './pages/AssetManagerPage.vue'

export default createRouter({
  history: createWebHistory('/static/'),
  routes: [
    { path: '/enhance', component: EnhancePage },
    { path: '/klein', component: KleinPage },
    { path: '/angle', component: AnglePage },
    { path: '/zimage', component: ZimagePage },
    { path: '/api-settings', component: ApiSettingsPage },
    { path: '/comfyui-settings', component: ComfyuiSettingsPage },
    { path: '/canvas-list', component: CanvasListPage },
    { path: '/asset-manager', component: AssetManagerPage },
  ]
})
