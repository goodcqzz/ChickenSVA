import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// 端口与 deploy/lib/ports.sh 一致：9800 对外，9801 后端
const publicPort = Number(process.env.CHICKENSV_PUBLIC_PORT || 9800)
const backendPort = Number(process.env.CHICKENSV_BACKEND_PORT || 9801)
const backendTarget = `http://127.0.0.1:${backendPort}`

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    port: publicPort,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        secure: false
      },
      '/ws': {
        target: backendTarget,
        ws: true,
        changeOrigin: true,
        secure: false
      }
    },
    hmr: {
      overlay: false
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          'element-plus': ['element-plus', '@element-plus/icons-vue'],
          'vendor': ['vue', 'vue-router', 'pinia', 'axios']
        }
      }
    }
  }
})
