import cv2
import mediapipe as mp
import math

def get_distance(p1, p2):
    return math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2)

def main():
    # Initialize MediaPipe Hands
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.5
    )
    mp_draw = mp.solutions.drawing_utils

    # Initialize Camera
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    print("Hand Gesture Tracking Started...")
    print("Press 'q' to quit.")

    while cap.isOpened():
        success, img = cap.read()
        if not success:
            print("Ignoring empty camera frame.")
            continue

        # Flip the image horizontally for a later selfie-view display
        img = cv2.flip(img, 1)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = hands.process(img_rgb)

        gesture = "None"

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                # Draw landmarks
                mp_draw.draw_landmarks(img, hand_landmarks, mp_hands.HAND_CONNECTIONS)

                # Get landmark positions
                lm = hand_landmarks.landmark
                
                # Check finger extension (True if extended)
                # Tips: 4, 8, 12, 16, 20
                # PIP/MCP for comparison
                index_extended = lm[8].y < lm[6].y
                middle_extended = lm[12].y < lm[10].y
                ring_extended = lm[16].y < lm[14].y
                pinky_extended = lm[20].y < lm[18].y
                
                # Thumb check
                thumb_extended = lm[4].x < lm[3].x if lm[5].x > lm[17].x else lm[4].x > lm[3].x

                # Gesture Logic
                if index_extended and middle_extended and ring_extended and pinky_extended:
                    gesture = "Open Palm"
                elif not index_extended and not middle_extended and not ring_extended and not pinky_extended:
                    gesture = "Closed Fist"
                elif index_extended and not middle_extended and not ring_extended and not pinky_extended:
                    # Directional Pointing Logic
                    tip = lm[8]
                    mcp = lm[5]
                    dx = tip.x - mcp.x
                    dy = tip.y - mcp.y
                    
                    if abs(dy) > abs(dx):
                        gesture = "Point Up" if dy < 0 else "Point Down"
                    else:
                        gesture = "Point Right" if dx > 0 else "Point Left"
                elif index_extended and middle_extended and not ring_extended and not pinky_extended:
                    gesture = "Peace Sign"
                
                # Pinch check (Thumb tip to Index tip distance)
                pinch_dist = get_distance(lm[4], lm[8])
                if pinch_dist < 0.05:
                    gesture = "Pinching"

                # Print gesture to console
                cv2.putText(img, gesture, (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 255, 0), 5)
                print(f"Detected Gesture: {gesture}")

        cv2.imshow("Hand Tracking", img)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
