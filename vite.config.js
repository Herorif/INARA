import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import provenance from './scripts/renderer-provenance.cjs'
const renderer = provenance.rendererProvenance()
const TOKEN = 'import.meta.env.VITE_INARA_SESSION_TOKEN'
const devTokenFile = path.join(path.dirname(fileURLToPath(import.meta.url)), '.runtime', 'dev-session-token')

// Dev only: the token of the running `npm run backend:dev` core (written per launch). An
// explicit VITE_INARA_SESSION_TOKEN wins. Builds always blank it; production renderers
// receive the token only from the Electron preload bridge.
const readDevToken = () => {
    try { return fs.readFileSync(devTokenFile, 'ascii').trim() } catch { return '' }
}
const devSessionToken = () => ({
    name: 'inara-dev-session-token',
    apply: 'serve',
    configureServer(server) {
        // A restarted dev core writes a new token; restart so clients reload with it.
        server.watcher.add(devTokenFile)
        const changed = file => { if (path.resolve(file) === devTokenFile) server.restart() }
        server.watcher.on('add', changed)
        server.watcher.on('change', changed)
    },
})

// https://vitejs.dev/config/
export default defineConfig(({ command }) => ({
    plugins: [renderer.plugin, react(), devSessionToken()],
    worker: { plugins: () => [renderer.workerPlugin()] },
    base: './', // Important for Electron
    define: {
        [TOKEN]: JSON.stringify(command === 'serve'
            ? process.env.VITE_INARA_SESSION_TOKEN || readDevToken()
            : ''),
    },
    server: {
        port: 5173,
    }
}))
