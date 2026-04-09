import { useEffect, useRef } from 'react';
import useStore from '../store';

/**
 * Captures mic audio data for the top-bar visualizer.
 * Reads selectedMicId from store, writes micAudioData back.
 */
export function useAudioVisualizer() {
    const selectedMicId = useStore(s => s.selectedMicId);
    const setMicAudioData = useStore(s => s.setMicAudioData);

    const audioContextRef = useRef(null);
    const analyserRef = useRef(null);
    const sourceRef = useRef(null);
    const animationFrameRef = useRef(null);

    const stop = () => {
        if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
        if (sourceRef.current) sourceRef.current.disconnect();
        if (audioContextRef.current) audioContextRef.current.close().catch(() => {});
        audioContextRef.current = null;
        analyserRef.current = null;
        sourceRef.current = null;
    };

    useEffect(() => {
        if (!selectedMicId) return;

        let cancelled = false;

        const start = async () => {
            stop();
            try {
                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: { deviceId: { exact: selectedMicId } }
                });
                if (cancelled) { stream.getTracks().forEach(t => t.stop()); return; }

                audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)();
                analyserRef.current = audioContextRef.current.createAnalyser();
                analyserRef.current.fftSize = 64;

                sourceRef.current = audioContextRef.current.createMediaStreamSource(stream);
                sourceRef.current.connect(analyserRef.current);

                const update = () => {
                    if (!analyserRef.current || cancelled) return;
                    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
                    analyserRef.current.getByteFrequencyData(dataArray);
                    setMicAudioData(Array.from(dataArray));
                    animationFrameRef.current = requestAnimationFrame(update);
                };
                update();
            } catch (err) {
                console.error('Error accessing microphone:', err);
            }
        };

        start();
        return () => { cancelled = true; stop(); };
    }, [selectedMicId, setMicAudioData]);
}
