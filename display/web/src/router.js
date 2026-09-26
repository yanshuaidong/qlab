import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from './layouts/MainLayout.vue'
import StockKline from './views/StockKline.vue'
import MarketFlow from './views/MarketFlow.vue'
import SectorFlow from './views/SectorFlow.vue'
import HsGt from './views/HsGt.vue'
import ReasonVector from './views/ReasonVector.vue'
import SignalAnalysis from './views/SignalAnalysis.vue'
import LimitAnalysis from './views/LimitAnalysis.vue'
import BlockTrade from './views/BlockTrade.vue'

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
        { path: 'limit-analysis', component: LimitAnalysis },
        { path: 'block-trade', component: BlockTrade },
        { path: 'sector', component: SectorFlow },
        { path: 'hsgt', component: HsGt },
        { path: 'reason-vector', component: ReasonVector },
        { path: 'signal-analysis', component: SignalAnalysis },
      ],
    },
  ],
})
