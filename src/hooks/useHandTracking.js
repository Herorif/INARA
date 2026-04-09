import { useEffect, useRef, useCallback } from 'react';
import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision';
import useStore from '../store';

/**
 * MediaPipe hand tracking: init, gesture detection, pinch/fist/drag, snap-to-button.
 * Drives the rAF loop that also calls processFrame from useVideoCapture.
 */
export function useHandTracking({ videoRef, canvasRef, isVideoOnRef, processFrame }) {
    const addMessage = useStore(s => s.addMessage);
    const setCursorPos = useStore(s => s.setCursorPos);
    const setIsPinching = useStore(s => s.setIsPinching);
    const setActiveDragElement = useStore(s => s.setActiveDragElement);
    const bringToFront = useStore(s => s.bringToFront);
    const setElementPositions = useStore(s => s.setElementPositions);

    const handLandmarkerRef = useRef(null);
    const lastVideoTimeRef = useRef(-1);
    const smoothedCursorPosRef = useRef({ x: 0, y: 0 });
    const snapStateRef = useRef({ isSnapped: false, element: null, snapPos: { x: 0, y: 0 } });
    const activeDragElementRef = useRef(null);
    const lastActiveDragElementRef = useRef(null);
    const lastWristPosRef = useRef({ x: 0, y: 0 });

    // Init HandLandmarker once
    useEffect(() => {
        let cancelled = false;
        const init = async () => {
            try {
                const response = await fetch('/hand_landmarker.task');
                if (!response.ok) throw new Error(`Model fetch failed: ${response.status}`);

                const vision = await FilesetResolver.forVisionTasks(
                    'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0/wasm'
                );
                if (cancelled) return;

                handLandmarkerRef.current = await HandLandmarker.createFromOptions(vision, {
                    baseOptions: { modelAssetPath: '/hand_landmarker.task', delegate: 'GPU' },
                    runningMode: 'VIDEO',
                    numHands: 1,
                });
                addMessage('System', 'Hand Tracking Ready');
            } catch (err) {
                console.error('Failed to initialize HandLandmarker:', err);
                addMessage('System', `Hand Tracking Error: ${err.message}`);
            }
        };
        init();
        return () => { cancelled = true; };
    }, [addMessage]);

    // Main rAF loop
    const loopRef = useRef(null);

    const predictWebcam = useCallback(() => {
        // Process video frame (draw + transmit + FPS)
        const shouldContinue = processFrame();
        if (shouldContinue === false) return; // video off

        const video = videoRef.current;
        const canvas = canvasRef.current;

        // Hand tracking
        const {
            isHandTrackingEnabled, cursorSensitivity, isCameraFlipped, isPinching, elementSizes
        } = useStore.getState();

        if (isHandTrackingEnabled && handLandmarkerRef.current && video && video.currentTime !== lastVideoTimeRef.current) {
            lastVideoTimeRef.current = video.currentTime;
            const results = handLandmarkerRef.current.detectForVideo(video, performance.now());

            if (results.landmarks && results.landmarks.length > 0) {
                const landmarks = results.landmarks[0];
                const indexTip = landmarks[8];
                const thumbTip = landmarks[4];

                const SENSITIVITY = cursorSensitivity;
                const rawX = isCameraFlipped ? (1 - indexTip.x) : indexTip.x;

                let normX = Math.max(0, Math.min(1, (rawX - 0.5) * SENSITIVITY + 0.5));
                let normY = Math.max(0, Math.min(1, (indexTip.y - 0.5) * SENSITIVITY + 0.5));

                const targetX = normX * window.innerWidth;
                const targetY = normY * window.innerHeight;

                // Smoothing
                const lerpFactor = 0.2;
                smoothedCursorPosRef.current.x += (targetX - smoothedCursorPosRef.current.x) * lerpFactor;
                smoothedCursorPosRef.current.y += (targetY - smoothedCursorPosRef.current.y) * lerpFactor;

                let finalX = smoothedCursorPosRef.current.x;
                let finalY = smoothedCursorPosRef.current.y;

                // Snap-to-button
                const SNAP_THRESHOLD = 50;
                const UNSNAP_THRESHOLD = 100;

                if (snapStateRef.current.isSnapped) {
                    const dist = Math.sqrt(
                        Math.pow(finalX - snapStateRef.current.snapPos.x, 2) +
                        Math.pow(finalY - snapStateRef.current.snapPos.y, 2)
                    );
                    if (dist > UNSNAP_THRESHOLD) {
                        if (snapStateRef.current.element) {
                            snapStateRef.current.element.classList.remove('snap-highlight');
                            snapStateRef.current.element.style.boxShadow = '';
                            snapStateRef.current.element.style.backgroundColor = '';
                            snapStateRef.current.element.style.borderColor = '';
                        }
                        snapStateRef.current = { isSnapped: false, element: null, snapPos: { x: 0, y: 0 } };
                    } else {
                        finalX = snapStateRef.current.snapPos.x;
                        finalY = snapStateRef.current.snapPos.y;
                    }
                } else {
                    const targets = Array.from(document.querySelectorAll('button, input, select, .draggable'));
                    let closest = null;
                    let minDist = Infinity;
                    for (const el of targets) {
                        const rect = el.getBoundingClientRect();
                        const centerX = rect.left + rect.width / 2;
                        const centerY = rect.top + rect.height / 2;
                        const dist = Math.sqrt(Math.pow(finalX - centerX, 2) + Math.pow(finalY - centerY, 2));
                        if (dist < minDist) { minDist = dist; closest = { el, centerX, centerY }; }
                    }
                    if (closest && minDist < SNAP_THRESHOLD) {
                        snapStateRef.current = { isSnapped: true, element: closest.el, snapPos: { x: closest.centerX, y: closest.centerY } };
                        finalX = closest.centerX;
                        finalY = closest.centerY;
                        closest.el.classList.add('snap-highlight');
                        closest.el.style.boxShadow = '0 0 20px rgba(34, 211, 238, 0.6)';
                        closest.el.style.backgroundColor = 'rgba(6, 182, 212, 0.2)';
                        closest.el.style.borderColor = 'rgba(34, 211, 238, 1)';
                    }
                }

                setCursorPos({ x: finalX, y: finalY });

                // Pinch detection
                const distance = Math.sqrt(Math.pow(indexTip.x - thumbTip.x, 2) + Math.pow(indexTip.y - thumbTip.y, 2));
                const isPinchNow = distance < 0.05;
                if (isPinchNow && !isPinching) {
                    const el = document.elementFromPoint(finalX, finalY);
                    if (el) {
                        const clickable = el.closest('button, input, a, [role="button"]');
                        if (clickable && typeof clickable.click === 'function') clickable.click();
                        else if (typeof el.click === 'function') el.click();
                    }
                }
                setIsPinching(isPinchNow);

                // Fist detection for dragging
                const isFingerFolded = (tipIdx, mcpIdx) => {
                    const tip = landmarks[tipIdx];
                    const mcp = landmarks[mcpIdx];
                    const wrist = landmarks[0];
                    const distTip = Math.sqrt(Math.pow(tip.x - wrist.x, 2) + Math.pow(tip.y - wrist.y, 2));
                    const distMcp = Math.sqrt(Math.pow(mcp.x - wrist.x, 2) + Math.pow(mcp.y - wrist.y, 2));
                    return distTip < distMcp;
                };

                const isFist = isFingerFolded(8, 5) && isFingerFolded(12, 9) && isFingerFolded(16, 13) && isFingerFolded(20, 17);

                const wrist = landmarks[0];
                const wristRawX = isCameraFlipped ? (1 - wrist.x) : wrist.x;
                const wristNormX = Math.max(0, Math.min(1, (wristRawX - 0.5) * SENSITIVITY + 0.5));
                const wristNormY = Math.max(0, Math.min(1, (wrist.y - 0.5) * SENSITIVITY + 0.5));
                const wristScreenX = wristNormX * window.innerWidth;
                const wristScreenY = wristNormY * window.innerHeight;

                if (isFist) {
                    if (!activeDragElementRef.current) {
                        const draggableElements = ['cad', 'browser', 'kasa', 'printer'];
                        for (const id of draggableElements) {
                            const el = document.getElementById(id);
                            if (el) {
                                const rect = el.getBoundingClientRect();
                                if (finalX >= rect.left && finalX <= rect.right && finalY >= rect.top && finalY <= rect.bottom) {
                                    activeDragElementRef.current = id;
                                    bringToFront(id);
                                    lastWristPosRef.current = { x: wristScreenX, y: wristScreenY };
                                    break;
                                }
                            }
                        }
                    }

                    if (activeDragElementRef.current) {
                        const dx = wristScreenX - lastWristPosRef.current.x;
                        const dy = wristScreenY - lastWristPosRef.current.y;
                        if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
                            const id = activeDragElementRef.current;
                            setElementPositions(prev => {
                                const currentPos = prev[id];
                                const size = elementSizes[id] || { w: 100, h: 100 };
                                let newX = currentPos.x + dx;
                                let newY = currentPos.y + dy;
                                const width = window.innerWidth;
                                const height = window.innerHeight;
                                newX = Math.max(size.w / 2, Math.min(width - size.w / 2, newX));
                                newY = Math.max(size.h / 2, Math.min(height - size.h / 2, newY));
                                return { ...prev, [id]: { x: newX, y: newY } };
                            });
                        }
                        lastWristPosRef.current = { x: wristScreenX, y: wristScreenY };
                    }
                } else {
                    activeDragElementRef.current = null;
                }

                if (activeDragElementRef.current !== lastActiveDragElementRef.current) {
                    setActiveDragElement(activeDragElementRef.current);
                    lastActiveDragElementRef.current = activeDragElementRef.current;
                }

                // Draw skeleton
                if (canvas) {
                    const ctx = canvas.getContext('2d');
                    ctx.strokeStyle = '#00FFFF';
                    ctx.lineWidth = 2;
                    const connections = HandLandmarker.HAND_CONNECTIONS;
                    for (const connection of connections) {
                        const start = landmarks[connection.start];
                        const end = landmarks[connection.end];
                        ctx.beginPath();
                        ctx.moveTo(start.x * canvas.width, start.y * canvas.height);
                        ctx.lineTo(end.x * canvas.width, end.y * canvas.height);
                        ctx.stroke();
                    }
                }
            }
        }

        if (isVideoOnRef.current) {
            loopRef.current = requestAnimationFrame(predictWebcam);
        }
    }, [processFrame, videoRef, canvasRef, isVideoOnRef, setCursorPos, setIsPinching, setActiveDragElement, bringToFront, setElementPositions]);

    // Start/stop loop when video toggles
    const isVideoOn = useStore(s => s.isVideoOn);
    const prevVideoOn = useRef(false);

    useEffect(() => {
        if (isVideoOn && !prevVideoOn.current) {
            // Video just turned on - start the loop
            setTimeout(() => {
                loopRef.current = requestAnimationFrame(predictWebcam);
            }, 100);
        } else if (!isVideoOn && prevVideoOn.current) {
            if (loopRef.current) cancelAnimationFrame(loopRef.current);
        }
        prevVideoOn.current = isVideoOn;
    }, [isVideoOn, predictWebcam]);
}
