import React, { useEffect, useRef } from 'react';

/**
 * INARA orb visualizer — 5-layer Canvas2D compositing stack.
 *
 * Draw order (back to front):
 *   Layer 1  Ambient glow      — large radial gradient, 4x core radius
 *   Layer 2  Inner halo        — tighter radial gradient, 1.8x core radius
 *   Layer 3  Spikes            — 90 lines from core edge, drawn before core so origins are hidden
 *   Layer 4  Tip flickers      — rare 1px dots at spike endpoints
 *   Layer 5  Core sphere       — radial gradient circle drawn on top; hides spike origins
 */
const Visualizer = ({ audioData, isListening, intensity = 0, width = 600, height = 400 }) => {
    const canvasRef = useRef(null);
    const intensityRef = useRef(intensity);
    const isListeningRef = useRef(isListening);

    useEffect(() => {
        intensityRef.current = intensity;
        isListeningRef.current = isListening;
    }, [intensity, isListening]);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');

        const SPIKE_COUNT = 90;
        const TWO_PI = Math.PI * 2;

        // Per-spike persistent state
        const spikePhases  = Array.from({ length: SPIKE_COUNT }, () => Math.random() * TWO_PI);
        const spikeSpeeds  = Array.from({ length: SPIKE_COUNT }, () => 0.3 + Math.random() * 0.7);

        let animationId;

        const draw = (time) => {
            const t  = time * 0.001;
            const w  = canvas.width;
            const h  = canvas.height;
            const cx = w / 2;
            const cy = h / 2;

            const amp      = intensityRef.current;           // 0–1
            const active   = isListeningRef.current;
            const speaking = active && amp > 0.15;

            // Core radius — small sphere, ~16px at 600px width
            const coreR = Math.min(w, h) * 0.055;

            // Pulse: core breathes at 0.6 Hz, ±4% size variation
            const pulse = 1 + 0.04 * Math.sin(t * TWO_PI * 0.6);
            const drawR = coreR * pulse;

            ctx.clearRect(0, 0, w, h);

            // ------------------------------------------------------------------
            // Layer 1 — Ambient glow (4x core radius, ~5% opacity at center)
            // ------------------------------------------------------------------
            const glowR = coreR * 4;
            const glowOpacity = speaking ? 0.05 + amp * 0.07
                : active ? 0.05
                : 0.03;

            const glowGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
            glowGrad.addColorStop(0,   `rgba(34, 211, 238, ${glowOpacity})`);
            glowGrad.addColorStop(0.5, `rgba(6, 182, 212, ${glowOpacity * 0.3})`);
            glowGrad.addColorStop(1,   'rgba(6, 182, 212, 0)');
            ctx.fillStyle = glowGrad;
            ctx.beginPath();
            ctx.arc(cx, cy, glowR, 0, TWO_PI);
            ctx.fill();

            // ------------------------------------------------------------------
            // Layer 2 — Inner halo (1.8x core radius, ~8% opacity)
            // ------------------------------------------------------------------
            const haloR = coreR * 1.8;
            const haloOpacity = speaking ? 0.08 + amp * 0.07
                : active ? 0.08
                : 0.05;

            const haloGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, haloR);
            haloGrad.addColorStop(0,   `rgba(34, 211, 238, ${haloOpacity})`);
            haloGrad.addColorStop(0.6, `rgba(6, 182, 212, ${haloOpacity * 0.4})`);
            haloGrad.addColorStop(1,   'rgba(6, 182, 212, 0)');
            ctx.fillStyle = haloGrad;
            ctx.beginPath();
            ctx.arc(cx, cy, haloR, 0, TWO_PI);
            ctx.fill();

            // ------------------------------------------------------------------
            // Layer 3 — Spikes (90 lines from core edge, drawn BEFORE core)
            // ------------------------------------------------------------------
            const spikeMaxLen = speaking ? coreR * (0.6 + amp * 1.2)
                : active    ? coreR * 0.4
                : coreR * 0.15;

            for (let i = 0; i < SPIKE_COUNT; i++) {
                const angle = (i / SPIKE_COUNT) * TWO_PI;
                const ph    = spikePhases[i];
                const sp    = spikeSpeeds[i];

                // Two-frequency drift: primary sway + slower underlying rhythm
                const drift = Math.sin(t * sp + ph) * 8
                            + Math.sin(t * sp * 0.4 + ph * 2) * 5;

                const normalizedDrift = (drift + 13) / 26;   // 0–1
                const len   = spikeMaxLen * (0.2 + 0.8 * normalizedDrift);
                const alpha = speaking ? 0.5 + normalizedDrift * 0.45
                    : active    ? 0.3 + normalizedDrift * 0.3
                    : 0.1 + normalizedDrift * 0.15;

                const x0 = cx + Math.cos(angle) * drawR;
                const y0 = cy + Math.sin(angle) * drawR;
                const x1 = cx + Math.cos(angle) * (drawR + len);
                const y1 = cy + Math.sin(angle) * (drawR + len);

                ctx.beginPath();
                ctx.moveTo(x0, y0);
                ctx.lineTo(x1, y1);
                ctx.strokeStyle = `rgba(34, 211, 238, ${alpha})`;
                ctx.lineWidth = speaking ? 1.5 : 1;
                ctx.stroke();

                // ------------------------------------------------------------------
                // Layer 4 — Tip flickers (0.4% chance per spike per frame)
                // ------------------------------------------------------------------
                const flickerThresh = speaking ? 0.01 + amp * 0.009
                    : active ? 0.003
                    : 0.001;

                if (Math.random() < flickerThresh) {
                    ctx.beginPath();
                    ctx.arc(x1, y1, 1, 0, TWO_PI);
                    ctx.fillStyle = `rgba(180, 240, 255, ${alpha * 2})`;
                    ctx.fill();
                }
            }

            // ------------------------------------------------------------------
            // Layer 5 — Core sphere (drawn last — covers spike origins)
            // ------------------------------------------------------------------
            const brightness = speaking ? 0.8 + amp * 0.2
                : active ? 0.8
                : 0.5 + Math.sin(t * 1.2) * 0.1;

            const coreGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, drawR);
            coreGrad.addColorStop(0,    `rgba(220, 250, 255, ${brightness})`);       // near-white specular
            coreGrad.addColorStop(0.3,  `rgba(34, 211, 238, ${brightness * 0.85})`); // bright cyan
            coreGrad.addColorStop(0.7,  `rgba(6, 182, 212, ${brightness * 0.5})`);   // darker cyan
            coreGrad.addColorStop(1,    `rgba(6, 182, 212, ${brightness * 0.05})`);  // transparent edge

            ctx.beginPath();
            ctx.arc(cx, cy, drawR, 0, TWO_PI);
            ctx.fillStyle = coreGrad;
            ctx.shadowBlur = speaking ? 30 + amp * 20 : active ? 18 : 10;
            ctx.shadowColor = 'rgba(34, 211, 238, 0.7)';
            ctx.fill();
            ctx.shadowBlur = 0;

            animationId = requestAnimationFrame(draw);
        };

        animationId = requestAnimationFrame(draw);
        return () => cancelAnimationFrame(animationId);
    }, [width, height]);

    return (
        <div className="relative" style={{ width, height }}>
            <canvas
                ref={canvasRef}
                style={{ width: '100%', height: '100%' }}
            />
        </div>
    );
};

export default Visualizer;
