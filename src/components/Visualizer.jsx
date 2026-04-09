import React, { useEffect, useRef } from 'react';

/**
 * JARVIS-style orb visualizer with ~90 radiating spikes.
 * Three states: idle (subtle drift), listening (moderate), speaking (intense).
 * Pure canvas - no DOM animation libs in the hot path.
 */
const Visualizer = ({ audioData, isListening, intensity = 0, width = 600, height = 400 }) => {
    const canvasRef = useRef(null);
    const audioDataRef = useRef(audioData);
    const intensityRef = useRef(intensity);
    const isListeningRef = useRef(isListening);

    useEffect(() => {
        audioDataRef.current = audioData;
        intensityRef.current = intensity;
        isListeningRef.current = isListening;
    }, [audioData, intensity, isListening]);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');

        const SPIKE_COUNT = 90;
        const TWO_PI = Math.PI * 2;

        // Per-spike random offsets for organic feel
        const spikePhases = Array.from({ length: SPIKE_COUNT }, () => Math.random() * TWO_PI);
        const spikeSpeeds = Array.from({ length: SPIKE_COUNT }, () => 0.3 + Math.random() * 0.7);

        let animationId;

        const draw = (time) => {
            const t = time * 0.001; // seconds
            const w = canvas.width;
            const h = canvas.height;
            const cx = w / 2;
            const cy = h / 2;
            const currentIntensity = intensityRef.current;
            const listening = isListeningRef.current;

            // Determine state
            const isSpeaking = listening && currentIntensity > 0.15;
            const isActive = listening;

            // Orb base radius scales to canvas
            const baseRadius = Math.min(w, h) * 0.12;

            ctx.clearRect(0, 0, w, h);

            // --- Outer glow (large soft circle) ---
            const glowIntensity = isSpeaking ? 0.12 + currentIntensity * 0.15
                : isActive ? 0.08
                : 0.04 + Math.sin(t * 0.8) * 0.02;
            const glowRadius = baseRadius * (isSpeaking ? 3.5 + currentIntensity * 2 : isActive ? 3.0 : 2.5);

            const glowGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowRadius);
            glowGrad.addColorStop(0, `rgba(34, 211, 238, ${glowIntensity})`);
            glowGrad.addColorStop(0.5, `rgba(6, 182, 212, ${glowIntensity * 0.4})`);
            glowGrad.addColorStop(1, 'rgba(6, 182, 212, 0)');
            ctx.fillStyle = glowGrad;
            ctx.beginPath();
            ctx.arc(cx, cy, glowRadius, 0, TWO_PI);
            ctx.fill();

            // --- Spikes ---
            const spikeBaseLen = baseRadius * 0.6;
            const spikeMaxExtra = isSpeaking ? baseRadius * 1.8 + currentIntensity * baseRadius * 2.5
                : isActive ? baseRadius * 0.6 + currentIntensity * baseRadius * 1.2
                : baseRadius * 0.15;

            for (let i = 0; i < SPIKE_COUNT; i++) {
                const angle = (i / SPIKE_COUNT) * TWO_PI;
                const phase = spikePhases[i];
                const speed = spikeSpeeds[i];

                // Organic per-spike oscillation
                const wave = Math.sin(t * speed * 2 + phase);
                const wave2 = Math.sin(t * speed * 3.7 + phase * 1.3);
                const combined = (wave * 0.6 + wave2 * 0.4);

                // Idle: very subtle. Active: moderate. Speaking: intense.
                const spikeLen = spikeBaseLen + spikeMaxExtra * Math.abs(combined);

                const innerX = cx + Math.cos(angle) * baseRadius;
                const innerY = cy + Math.sin(angle) * baseRadius;
                const outerX = cx + Math.cos(angle) * (baseRadius + spikeLen);
                const outerY = cy + Math.sin(angle) * (baseRadius + spikeLen);

                // Spike opacity varies with length
                const alpha = isSpeaking ? 0.5 + Math.abs(combined) * 0.5
                    : isActive ? 0.3 + Math.abs(combined) * 0.4
                    : 0.15 + Math.abs(combined) * 0.2;

                ctx.beginPath();
                ctx.moveTo(innerX, innerY);
                ctx.lineTo(outerX, outerY);
                ctx.strokeStyle = `rgba(34, 211, 238, ${alpha})`;
                ctx.lineWidth = isSpeaking ? 1.5 : 1;
                ctx.stroke();
            }

            // --- Core sphere (filled gradient) ---
            const coreGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, baseRadius);
            const coreBrightness = isSpeaking ? 0.9 + currentIntensity * 0.1
                : isActive ? 0.7
                : 0.4 + Math.sin(t * 1.2) * 0.1;
            coreGrad.addColorStop(0, `rgba(180, 240, 255, ${coreBrightness})`);
            coreGrad.addColorStop(0.4, `rgba(34, 211, 238, ${coreBrightness * 0.7})`);
            coreGrad.addColorStop(0.8, `rgba(6, 182, 212, ${coreBrightness * 0.4})`);
            coreGrad.addColorStop(1, `rgba(6, 182, 212, ${coreBrightness * 0.1})`);

            ctx.beginPath();
            ctx.arc(cx, cy, baseRadius, 0, TWO_PI);
            ctx.fillStyle = coreGrad;
            ctx.fill();

            // --- Core ring (sharp edge) ---
            const ringAlpha = isSpeaking ? 0.8 : isActive ? 0.5 : 0.25 + Math.sin(t * 1.5) * 0.1;
            ctx.beginPath();
            ctx.arc(cx, cy, baseRadius, 0, TWO_PI);
            ctx.strokeStyle = `rgba(34, 211, 238, ${ringAlpha})`;
            ctx.lineWidth = 1.5;
            ctx.shadowBlur = isSpeaking ? 25 : isActive ? 15 : 8;
            ctx.shadowColor = 'rgba(34, 211, 238, 0.6)';
            ctx.stroke();
            ctx.shadowBlur = 0;

            // --- Inner detail ring (subtle) ---
            const innerRingR = baseRadius * 0.6;
            const innerAlpha = isSpeaking ? 0.3 : isActive ? 0.15 : 0.08;
            ctx.beginPath();
            ctx.arc(cx, cy, innerRingR, 0, TWO_PI);
            ctx.strokeStyle = `rgba(34, 211, 238, ${innerAlpha})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();

            // --- Label ---
            const fontSize = Math.min(w, h) * 0.04;
            ctx.font = `bold ${fontSize}px "Segoe UI", system-ui, sans-serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = `rgba(200, 240, 255, ${isSpeaking ? 0.95 : isActive ? 0.8 : 0.5 + Math.sin(t * 1.2) * 0.15})`;
            ctx.shadowBlur = 15;
            ctx.shadowColor = 'rgba(34, 211, 238, 0.8)';
            ctx.fillText('I.N.A.R.A', cx, cy);
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
