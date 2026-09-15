<template>
  <el-container class="layout">
    <el-aside width="220px" class="sidebar">
      <div class="sidebar-logo"><span>QLab</span> 股票数据</div>
      <el-menu
        :default-active="route.path"
        router
        class="sidebar-menu"
      >
        <el-menu-item index="/kline">
          <el-icon><TrendCharts /></el-icon>
          <span>个股K线</span>
        </el-menu-item>
        <el-menu-item index="/market">
          <el-icon><DataAnalysis /></el-icon>
          <span>大盘资金流</span>
        </el-menu-item>
        <el-menu-item index="/sector">
          <el-icon><Grid /></el-icon>
          <span>板块资金流</span>
        </el-menu-item>
        <el-menu-item index="/hsgt">
          <el-icon><Connection /></el-icon>
          <span>沪深港通</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-main class="content">
      <RouterView />
    </el-main>
  </el-container>
</template>

<script setup>
import { useRoute } from 'vue-router'

const route = useRoute()
</script>
