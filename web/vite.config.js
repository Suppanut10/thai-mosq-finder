import { defineConfig } from 'vite'

// base './' ให้ใช้ได้ทั้งบน GitHub Pages (username.github.io/<repo>/) และ dev server
export default defineConfig({
  base: './',
  server: { host: true },
})
