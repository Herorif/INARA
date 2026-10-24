import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import provenance from './scripts/renderer-provenance.cjs'
const renderer = provenance.rendererProvenance()

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [renderer.plugin, react()],
    worker: { plugins: () => [renderer.workerPlugin()] },
    base: './', // Important for Electron
    server: {
        port: 5173,
    }
})
