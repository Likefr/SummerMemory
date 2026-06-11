import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: process.env.NODE_ENV === 'production' ? './' : '/',
  build: {
    assetsDir: 'static',
    rollupOptions: {
      onwarn(warning, warn) {
        // Suppress gl-bench CJS warning from @cosmograph/cosmograph
        if (warning.code === 'MODULE_LEVEL_DIRECTIVE') return
        warn(warning)
      }
    },
    commonjsOptions: {
      include: [/node_modules/],
      transformMixedEsModules: true,
    }
  },
  optimizeDeps: {
    include: ['@cosmograph/cosmograph', 'gl-bench']
  },
  resolve: {
    alias: {
      'gl-bench': 'gl-bench/dist/gl-bench.module.js'
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api/memory': {
        target: 'http://localhost:11435',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/memory/, '')
      }
    }
  }
})
