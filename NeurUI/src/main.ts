import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, PieChart, GraphChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import './styles/global.css'

// echarts 按需注册（Dashboard 等页面的图表区使用；vendor-charts 已在 vite
// manualChunks 中分组，按需 chunk 化不影响首屏）
use([
  CanvasRenderer,
  LineChart,
  BarChart,
  PieChart,
  GraphChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
])

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(i18n)
app.use(Antd)
app.component('VChart', VChart)

app.mount('#app')
