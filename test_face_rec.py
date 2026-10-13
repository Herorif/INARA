import face_recognition
import numpy as np
import cv2
import sys

print(f"Numpy version: {np.__version__}")
print(f"CV2 version: {cv2.__version__}")

try:
    print("Attempting to load image with face_recognition...")
    # Create a dummy image if reference.jpg doesn't exist (but we know it does)
    # Actually let's just make a dummy numpy array to test valid format
    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
    
    print("Encoding dummy image...")
    try:
        enc = face_recognition.face_encodings(dummy_img)
        print("Dummy encoding successful (empty result expected)")
    except Exception as e:
        print(f"Dummy encoding failed: {e}")

    print("Loading actual reference.jpg using CV2...")
    # image = face_recognition.load_image_file("backend/reference.jpg") # This uses PIL
    img_bgr = cv2.imread("backend/reference.jpg")
    if img_bgr is None:
        raise ValueError("Failed to load image with cv2")
    image = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    
    # Force contiguous array and uint8 just to be safe
    image = np.ascontiguousarray(image, dtype=np.uint8)
    
    print(f"Image loaded. Shape: {image.shape}, Dtype: {image.dtype}, Flags: {image.flags}")
    
    encodings = face_recognition.face_encodings(image)
    print(f"Encodings found: {len(encodings)}")

except Exception as e:
    print(f"CRITICAL ERROR: {e}")
    import traceback
    traceback.print_exc()
