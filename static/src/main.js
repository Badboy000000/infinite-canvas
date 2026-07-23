import { createApp } from 'vue'
import App from './App.vue'

// 挂载到 #app 容器(与 legacy HTML 页面并行 · 不冲突)
const app = createApp(App)
app.mount('#app')