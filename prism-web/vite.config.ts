import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 登录门禁（Step7 审查⑤实锤修复）：/auth 不在枚举表 → 浏览器登录 404（单测/runner 直连 8002 才全绿）
      '/auth': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/chat/stream': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/chat/abort': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/dashboard': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/session': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8002', ws: true, changeOrigin: true },
      // 舆情 Board iframe 内部用绝对路径 /static/... 加载 JS/CSS，
      // 走 Prism 反代 /sentiment-board/ 时资源会断，这里直接代理到舆情 Board
      '/sentiment-board': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      // Prism Dashboards 子服务（口碑/配置/市场）→ prism-api /dash/ 反代 → :8010
      '/dash': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/static': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/api/dashboard': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      // T-5.3/T-5.11：ui-response + events 代理
      '/ui-response': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/events': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/identity': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      // 社媒深挖能力包 M3：xlsx 导出下载 + TikHub 状态
      '/export': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/tikhub': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/skills': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      // 用户反馈（2026-11-04）：右下角入口 → prism-api POST /feedback
      '/feedback': { target: 'http://127.0.0.1:8002', changeOrigin: true },
    },
  },
});
