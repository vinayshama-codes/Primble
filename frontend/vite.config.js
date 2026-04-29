import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  // In production builds, refuse to bake in a localhost API URL.
  // This catches the most common misconfiguration: forgetting to set VITE_API_BASE.
  if (mode === 'production') {
    const apiBase = env.VITE_API_BASE || ''
    if (!apiBase) {
      throw new Error(
        'VITE_API_BASE is not set. Set it to your production API URL before building.'
      )
    }
    if (/localhost|127\.0\.0\.1|0\.0\.0\.0/.test(apiBase)) {
      throw new Error(
        `VITE_API_BASE="${apiBase}" looks like a local address. ` +
        'Set it to your production API URL.'
      )
    }
  }

  return {
    plugins: [react()],
  }
})
