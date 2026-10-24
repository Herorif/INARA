// Geometry only: no capture, inference or application actions.
export const HAND_CONNECTIONS = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20]];
export function validHands(result) {
  return (result?.landmarks || []).slice(0, 2).filter(hand => hand.length === 21 && hand.every(point => Number.isFinite(point.x) && Number.isFinite(point.y)));
}
export function drawOverlay(canvas, result, {
  width = 640,
  height = 480,
  mode = 'skeleton'
} = {}) {
  if (!canvas) return;
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) return;
  context.clearRect(0, 0, width, height);
  if (mode === 'off') return;
  validHands(result).forEach((hand, index) => {
    const color = index === 0 ? '#86edf2' : '#ffc987';
    context.strokeStyle = color;
    context.fillStyle = color;
    context.lineWidth = Math.max(2, width / 300);
    if (mode === 'skeleton') for (const [a, b] of HAND_CONNECTIONS) {
      context.beginPath();
      context.moveTo(hand[a].x * width, hand[a].y * height);
      context.lineTo(hand[b].x * width, hand[b].y * height);
      context.stroke();
    }
    for (const point of hand) {
      context.beginPath();
      context.arc(point.x * width, point.y * height, Math.max(2.5, width / 210), 0, Math.PI * 2);
      context.fill();
    }
  });
}
