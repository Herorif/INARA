print("Importing sys...")
import sys

print("Importing PySide6...")
try:
    from PySide6.QtWidgets import QApplication
    print("PySide6 imported successfully")
except ImportError as e:
    print(f"PySide6 failed: {e}")

print("Importing cv2...")
try:
    import cv2
    print("cv2 imported successfully")
except ImportError as e:
    print(f"cv2 failed: {e}")

print("Importing numpy...")
try:
    import numpy
    print("numpy imported successfully")
except ImportError as e:
    print(f"numpy failed: {e}")
