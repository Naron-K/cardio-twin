import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Where the CardioTwin backend is. 8000 unless CARDIOTWIN_API says otherwise,
// for a machine where something else already holds port 8000.
const api = process.env.CARDIOTWIN_API ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': api,
      '/presets': api,
      '/ws': {
        target: api,
        ws: true,
      },
    },
  },
})
