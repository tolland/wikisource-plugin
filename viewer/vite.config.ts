import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');

  return {
    plugins: [sveltekit()],
    server: {
      host: '127.0.0.1',
      proxy: {
        '/api': {
          target: env.WTBOT_API_URL ?? 'http://127.0.100.1:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, '')
        }
      }
    }
  };
});
