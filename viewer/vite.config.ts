import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    host: '127.0.0.1',
    // Dev-convention ports (see docs/logging.md): 18563 viewer, 18564 wtbot.
    port: 18563,
    proxy: {
      '/api': {
        target: 'http://127.0.100.1:18564',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
});
