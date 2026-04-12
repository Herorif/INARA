import { useRef, useCallback } from 'react';
import useStore from '../store';
import socket from '../services/socket';

/**
 * Manages webcam start/stop, frame transmission, and FPS counting.
 * Returns { videoRef, canvasRef, startVideo, stopVideo, toggleVideo }.
 * The predictWebcam loop and hand tracking are handled in useHandTracking.
 */
export function useVideoCapture() {
    const selectedWebcamId = useStore(s => s.selectedWebcamId);
    const setIsVideoOn = useStore(s => s.setIsVideoOn);
    const setFps = useStore(s => s.setFps);
    const addMessage = useStore(s => s.addMessage);

    const videoRef = useRef(null);
    const canvasRef = useRef(null);
    const transmissionCanvasRef = useRef(null);
    const isVideoOnRef = useRef(false);
    const frameCountRef = useRef(0);
    const lastFrameTimeRef = useRef(0);

    const startVideo = useCallback(async () => {
        try {
            const constraints = {
                video: {
                    width: { ideal: 1920 },
                    height: { ideal: 1080 },
                    aspectRatio: 16 / 9,
                }
            };
            if (selectedWebcamId) {
                constraints.video.deviceId = { exact: selectedWebcamId };
            }

            const stream = await navigator.mediaDevices.getUserMedia(constraints);
            if (videoRef.current) {
                videoRef.current.srcObject = stream;
                videoRef.current.play();
            }

            if (!transmissionCanvasRef.current) {
                transmissionCanvasRef.current = document.createElement('canvas');
                transmissionCanvasRef.current.width = 640;
                transmissionCanvasRef.current.height = 360;
            }

            setIsVideoOn(true);
            isVideoOnRef.current = true;
        } catch (err) {
            console.error('Error accessing camera:', err);
            addMessage('System', 'Error accessing camera');
        }
    }, [selectedWebcamId, setIsVideoOn, addMessage]);

    const stopVideo = useCallback(() => {
        if (videoRef.current && videoRef.current.srcObject) {
            videoRef.current.srcObject.getTracks().forEach(track => track.stop());
            videoRef.current.srcObject = null;
        }
        setIsVideoOn(false);
        isVideoOnRef.current = false;
        setFps(0);
    }, [setIsVideoOn, setFps]);

    const toggleVideo = useCallback(() => {
        if (isVideoOnRef.current) {
            stopVideo();
        } else {
            startVideo();
        }
    }, [startVideo, stopVideo]);

    /** Called from the rAF loop to send a frame to backend + count FPS. */
    const processFrame = useCallback(() => {
        if (!videoRef.current || !canvasRef.current || !isVideoOnRef.current) return false;
        if (videoRef.current.readyState < 2 || videoRef.current.videoWidth === 0) return true; // keep looping

        const ctx = canvasRef.current.getContext('2d');
        if (canvasRef.current.width !== videoRef.current.videoWidth || canvasRef.current.height !== videoRef.current.videoHeight) {
            canvasRef.current.width = videoRef.current.videoWidth;
            canvasRef.current.height = videoRef.current.videoHeight;
        }
        ctx.drawImage(videoRef.current, 0, 0, canvasRef.current.width, canvasRef.current.height);

        // Transmit every 5th frame
        const { aiConnected } = useStore.getState();
        if (aiConnected && frameCountRef.current % 5 === 0) {
            const transCanvas = transmissionCanvasRef.current;
            if (transCanvas) {
                const transCtx = transCanvas.getContext('2d');
                transCtx.drawImage(videoRef.current, 0, 0, transCanvas.width, transCanvas.height);
                transCanvas.toBlob((blob) => {
                    if (blob) socket.emit('video_frame', { image: blob });
                }, 'image/jpeg', 0.6);
            }
        }

        // FPS
        const now = performance.now();
        frameCountRef.current++;
        if (now - lastFrameTimeRef.current >= 1000) {
            setFps(frameCountRef.current);
            frameCountRef.current = 0;
            lastFrameTimeRef.current = now;
        }

        return isVideoOnRef.current;
    }, [setFps]);

    return {
        videoRef,
        canvasRef,
        isVideoOnRef,
        transmissionCanvasRef,
        startVideo,
        stopVideo,
        toggleVideo,
        processFrame,
    };
}
