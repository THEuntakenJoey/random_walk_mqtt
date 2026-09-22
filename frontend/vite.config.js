import { defineConfig } from 'vite';

const BACKEND_HOST = process.env.VITE_BACKEND_HOST || 'localhost';

export default defineConfig({
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: `http://${BACKEND_HOST}:8000`,
        changeOrigin: true
      },
      '/ws': {
        target: `ws://${BACKEND_HOST}:8000`,
        ws: true
      }
    }
  }
});
