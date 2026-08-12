import { defineConfig } from 'vite';
import { resolve } from 'path';
import react from '@vitejs/plugin-react-swc';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        diagnostics: resolve(__dirname, 'diagnostics.html'),
      },
    },
  },
  server: {
    proxy: {
      '/connect': {
        target: 'http://0.0.0.0:7860',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://0.0.0.0:7860',
        changeOrigin: true,
      },
    },
  },
});
