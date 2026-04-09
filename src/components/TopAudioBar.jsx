import React, { useEffect, useRef } from 'react';
import useStore from '../store';

const TopAudioBar = () => {
    const audioData = useStore(s => s.micAudioData);
    const canvasRef = useRef(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');

        const draw = () => {
            const width = canvas.width;
            const height = canvas.height;
            ctx.clearRect(0, 0, width, height);

            const barWidth = 4;
            const gap = 2;
            const totalBars = Math.floor(width / (barWidth + gap));
            const center = width / 2;

            for (let i = 0; i < totalBars / 2; i++) {
                const value = audioData[i % audioData.length] || 0;
                const percent = value / 255;
                const barHeight = Math.max(2, percent * height);

                ctx.fillStyle = `rgba(34, 211, 238, ${0.2 + percent * 0.8})`;
                ctx.fillRect(center + i * (barWidth + gap), (height - barHeight) / 2, barWidth, barHeight);
                ctx.fillRect(center - (i + 1) * (barWidth + gap), (height - barHeight) / 2, barWidth, barHeight);
            }
        };

        requestAnimationFrame(draw);
    }, [audioData]);

    return (
        <canvas
            ref={canvasRef}
            width={300}
            height={40}
            className="opacity-80"
        />
    );
};

export default TopAudioBar;
