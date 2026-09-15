import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from './layouts/MainLayout.vue'
import StockKline from './views/StockKline.vue'
import MarketFlow from './views/MarketFlow.vue'
import SectorFlow from './views/SectorFlow.vue'
import HsGt from './views/HsGt.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: MainLayout,
      children: [
        { path: '', redirect: '/kline' },
        { path: 'kline', component: StockKline },
        { path: 'market', component: MarketFlow },
        { path: 'sector', component: SectorFlow },
        { path: 'hsgt', component: HsGt },
      ],
    },
  ],
})
