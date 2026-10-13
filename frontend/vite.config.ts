import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            // Group heavy UI and data visualization libraries
            if (id.includes('recharts') || id.includes('lucide-react')) {
              return 'vendor-ui'
            }
            // Group core React ecosystem libraries
            if (id.includes('react') || id.includes('react-dom') || id.includes('@tanstack')) {
              return 'vendor-react'
            }
            // Returning undefined lets Rollup naturally handle other small 
            // packages, preventing circular references!
          }
        },
      },
    },
    chunkSizeWarningLimit: 600,
  },
})