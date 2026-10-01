import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `base: '/admin/'` harus sama dengan UI_PREFIX di app/application.py: berkas
// hasil build direferensikan sebagai /admin/assets/... oleh index.html.
//
// Di pengembangan, `/api` diproksikan ke FastAPI supaya browser melihat
// permintaan itu sebagai **same-origin**. Itu bukan sekadar menghindari CORS:
// cookie sesi (`SameSite=Lax`, HttpOnly) tidak akan ikut terkirim pada
// permintaan lintas-origin, sehingga login akan tampak berhasil tetapi
// sesinya tidak pernah terbaca.
export default defineConfig({
  base: '/admin/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
})
