import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import provenance from './scripts/renderer-provenance.cjs'
const renderer = provenance.rendererProvenance()
const TOKEN = 'import.meta.env.VITE_JARVIS_SESSION_TOKEN'
const devTokenFile = path.join(path.dirname(fileURLToPath(import.meta.url)), '.runtime', 'dev-session-token')

// Dev only: the token of the running `npm run backend:dev` core (written per launch). An
// explicit VITE_JARVIS_SESSION_TOKEN wins. Builds always blank it; production renderers
// receive the token only from the Electron preload bridge.
const readDevToken = () => {
    try { return fs.readFileSync(devTokenFile, 'ascii').trim() } catch { return '' }
}
// Renamed from INARA on 5 Nov 2026: the pre-rename variable still works for one release, with
// one deprecation warning (the value is never printed).
const LEGACY_TOKEN_ENV = 'VITE_INARA_SESSION_TOKEN'
let warnedLegacyToken = false
const explicitDevToken = () => {
    if (process.env.VITE_JARVIS_SESSION_TOKEN) return process.env.VITE_JARVIS_SESSION_TOKEN
    const legacy = process.env[LEGACY_TOKEN_ENV]
    if (legacy && !warnedLegacyToken) {
        warnedLegacyToken = true
        console.warn(`${LEGACY_TOKEN_ENV} is deprecated; set VITE_JARVIS_SESSION_TOKEN instead.`)
    }
    return legacy || ''
}
const devSessionToken = () => ({
    name: 'jarvis-dev-session-token',
    apply: 'serve',
    configureServer(server) {
        // A restarted dev core writes a new token; restart so clients reload with it.
        server.watcher.add(devTokenFile)
        const changed = file => { if (path.resolve(file) === devTokenFile) server.restart() }
        server.watcher.on('add', changed)
        server.watcher.on('change', changed)
    },
})

// Production only: a strict CSP for the built file:// renderer. `npm run dev` keeps Vite's
// inline HMR client and has no CSP. The core socket is http/ws://localhost:8000 (src/services/socket.js).
// frame-ancestors is omitted: Chromium ignores it in a <meta> policy and logs a console error.
// No 'wasm-unsafe-eval': MediaPipe's WASM compiles only inside the file:// tracking worker, which
// does not inherit this document policy; the document itself never compiles WASM.
const CONTENT_SECURITY_POLICY = [
    "default-src 'self'",
    "script-src 'self'",
    "worker-src 'self' blob:",
    "style-src 'self'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self' http://localhost:8000 ws://localhost:8000",
    "media-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
].join('; ')
const contentSecurityPolicy = () => ({
    name: 'jarvis-content-security-policy',
    apply: 'build',
    transformIndexHtml: {
        order: 'post',
        handler(html) {
            // Scripts and styles must be external 'self' files (the <html> background attribute is
            // parsed before the meta exists, so it is not subject to the policy).
            if (/<script(?![^>]*\ssrc=)[^>]*>|<style[\s>]/i.test(html)) throw Error('Inline <script>/<style> in index.html would need a weaker CSP')
            const charset = /<meta charset="UTF-8" \/>/i
            if (!charset.test(html) || /Content-Security-Policy/i.test(html)) throw Error('Cannot place the Content-Security-Policy meta')
            return html.replace(charset, match => `${match}\n    <meta http-equiv="Content-Security-Policy" content="${CONTENT_SECURITY_POLICY}" />`)
        },
    },
})

// https://vitejs.dev/config/
export default defineConfig(({ command }) => ({
    plugins: [renderer.plugin, react(), devSessionToken(), contentSecurityPolicy()],
    worker: { plugins: () => [renderer.workerPlugin()] },
    base: './', // Important for Electron
    define: {
        [TOKEN]: JSON.stringify(command === 'serve'
            ? explicitDevToken() || readDevToken()
            : ''),
    },
    build: {
        // Keep small scripts (the speech AudioWorklet) as 'self' files: a data: URL would be
        // blocked by script-src 'self'. Other assets keep Vite's default inlining.
        assetsInlineLimit: file => (/\.[cm]?js$/i.test(file) ? false : undefined),
    },
    server: {
        port: 5173,
    }
}))
