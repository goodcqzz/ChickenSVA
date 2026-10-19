<template>
  <div class="app-container">
    <router-view :key="route.fullPath" />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

onMounted(() => {
  console.log('鸡基因组智能体框架已启动')
})
</script>

<style>
:root {
  --bio-primary: #0D9488;
  --bio-primary-light: #14B8A6;
  --bio-primary-lighter: #5EEAD4;
  --bio-primary-dark: #0F766E;
  --bio-secondary: #06B6D4;
  --bio-secondary-light: #22D3EE;
  --bio-accent: #10B981;
  --bio-accent-light: #34D399;
  --bio-gene-a: #0D9488;
  --bio-gene-t: #F59E0B;
  --bio-gene-c: #8B5CF6;
  --bio-gene-g: #EF4444;
  --bio-bg-dark: #0C1222;
  --bio-bg-darker: #080E1A;
  --bio-bg-card: #111827;
  --bio-bg-card-hover: #1F2937;
  --bio-bg-light: #F0FDFA;
  --bio-bg-lighter: #F8FAFC;
  --bio-border: #1E3A5F;
  --bio-border-light: #E2E8F0;
  --bio-text-primary: #F1F5F9;
  --bio-text-secondary: #94A3B8;
  --bio-text-dark: #374151;
  --bio-text-muted: #64748B;
  --bio-shadow: 0 4px 24px rgba(13, 148, 136, 0.12);
  --bio-shadow-lg: 0 8px 40px rgba(13, 148, 136, 0.18);
  --bio-radius: 12px;
  --bio-radius-lg: 16px;
  --bio-gradient-primary: linear-gradient(135deg, #0D9488 0%, #06B6D4 100%);
  --bio-gradient-dark: linear-gradient(135deg, #0C1222 0%, #0F172A 50%, #0C1222 100%);
  --bio-gradient-card: linear-gradient(135deg, rgba(13, 148, 136, 0.08) 0%, rgba(6, 182, 212, 0.08) 100%);
  --bio-glow: 0 0 20px rgba(13, 148, 136, 0.3);
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background-color: #ffffff;
  color: var(--bio-text-dark);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  overflow-y: auto;
}

.app-container {
  width: 100vw;
  min-height: 100vh;
  height: auto;
  overflow-x: hidden;
  overflow-y: auto;
  background: #ffffff;
}

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: rgba(13, 148, 136, 0.25);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(13, 148, 136, 0.4);
}

code, pre, .mono {
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
}

.el-button--primary {
  --el-button-bg-color: var(--bio-primary);
  --el-button-border-color: var(--bio-primary);
  --el-button-hover-bg-color: var(--bio-primary-light);
  --el-button-hover-border-color: var(--bio-primary-light);
  --el-button-active-bg-color: var(--bio-primary-dark);
  --el-button-active-border-color: var(--bio-primary-dark);
}

.el-tag--success {
  --el-tag-bg-color: rgba(16, 185, 129, 0.1);
  --el-tag-border-color: rgba(16, 185, 129, 0.3);
  --el-tag-text-color: #10B981;
}

.el-tag--warning {
  --el-tag-bg-color: rgba(245, 158, 11, 0.1);
  --el-tag-border-color: rgba(245, 158, 11, 0.3);
  --el-tag-text-color: #F59E0B;
}

.el-tag--info {
  --el-tag-bg-color: rgba(6, 182, 212, 0.1);
  --el-tag-border-color: rgba(6, 182, 212, 0.3);
  --el-tag-text-color: #06B6D4;
}

.el-radio-button__original-radio:checked + .el-radio-button__inner {
  background-color: var(--bio-primary);
  border-color: var(--bio-primary);
}

.el-switch.is-checked .el-switch__core {
  background-color: var(--bio-primary);
  border-color: var(--bio-primary);
}

.el-slider__bar {
  background-color: var(--bio-primary);
}

.el-slider__button {
  border-color: var(--bio-primary);
}

.el-step__head.is-finish {
  color: var(--bio-primary);
  border-color: var(--bio-primary);
}

.el-step__title.is-finish {
  color: var(--bio-primary);
}

.el-step__head.is-process {
  color: var(--bio-primary);
  border-color: var(--bio-primary);
}

.el-progress-bar__inner {
  background-color: var(--bio-primary);
}

.el-input__wrapper:focus-within {
  box-shadow: 0 0 0 1px var(--bio-primary) inset;
}
</style>
