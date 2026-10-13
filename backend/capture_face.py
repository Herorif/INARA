import cv2
import os

def capture_reference_face(output_path="reference.jpg"):
    """
    Opens the webcam and captures a frame when the user presses 's' or 'Space'.
    Saves the frame to the specified output path.
    """
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    print("Press 's' or 'SPACE' to capture your face.")
    print("Press 'q' or 'ESC' to quit without saving.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Failed to capture frame.")
            break

        # Display the resulting frame
        cv2.imshow('Capture Reference Face', frame)

        key = cv2.waitKey(1) & 0xFF

        # 's' or SPACE to save
        if key == ord('s') or key == 32:
            cv2.imwrite(output_path, frame)
            print(f"Reference face saved to {output_path}")
            break
        
        # 'q' or ESC to quit
        if key == ord('q') or key == 27:
            print("Capture cancelled.")
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    # Ensure backend directory context
    script_dir = os.path.dirname(os.path.abspath(__file__))
    save_path = os.path.join(script_dir, "reference.jpg")
    capture_reference_face(save_path)
