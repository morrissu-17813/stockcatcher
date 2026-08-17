// 檔案位置: tide-dashboard/vite.config.js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  // 🚨 這裡就是把「翻譯官」註冊進 Vite 的關鍵
  plugins: [vue()],
  server: {
    port: 5173,
  }
})