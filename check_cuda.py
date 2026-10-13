import cv2
try:
    count = cv2.cuda.getCudaEnabledDeviceCount()
    print(f"CUDA Devices: {count}")
except AttributeError:
    print("CUDA module not found in cv2")
