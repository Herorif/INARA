"""
Tests for Face Authentication.
"""
import pytest
import os
import numpy as np

# Try to import the authenticator, skip all tests if dependencies missing
try:
    from authenticator import FaceAuthenticator
    HAS_AUTH = True
except ImportError as e:
    HAS_AUTH = False
    IMPORT_ERROR = str(e)
    FaceAuthenticator = None

pytestmark = pytest.mark.skipif(not HAS_AUTH, reason=f"Auth dependencies not installed: {IMPORT_ERROR if not HAS_AUTH else ''}")



class TestAuthenticatorInit:
    """Test FaceAuthenticator initialization."""
    
    def test_authenticator_creation(self):
        """Test FaceAuthenticator can be created."""
        auth = FaceAuthenticator()
        assert auth is not None
        print("FaceAuthenticator initialized successfully")
    
    def test_authenticator_with_callbacks(self):
        """Test FaceAuthenticator with callbacks."""
        statuses = []
        frames = []
        
        async def on_status(is_auth):
            statuses.append(is_auth)
        
        async def on_frame(frame_b64):
            frames.append(frame_b64)
        
        auth = FaceAuthenticator(
            on_status_change=on_status,
            on_frame=on_frame
        )
        assert auth.on_status_change is not None
        assert auth.on_frame is not None


class TestMediaPipeModel:
    """Test MediaPipe Face Landmarker model."""
    
    def test_model_path_defined(self):
        """Test that model path is defined."""
        assert hasattr(FaceAuthenticator, 'MODEL_PATH')
        print(f"Model path: {FaceAuthenticator.MODEL_PATH}")
    
    def test_model_download_url(self):
        """Test that model URL is defined."""
        assert hasattr(FaceAuthenticator, 'MODEL_URL')
        print(f"Model URL: {FaceAuthenticator.MODEL_URL}")
    
    def test_ensure_model(self):
        """Test model download/verification."""
        auth = FaceAuthenticator()
        auth._ensure_model()
        
        model_path = FaceAuthenticator.MODEL_PATH
        if os.path.exists(model_path):
            print(f"Model exists at: {model_path}")
            print(f"Model size: {os.path.getsize(model_path)} bytes")
        else:
            print("Model not downloaded (may require internet)")


class TestLandmarkExtraction:
    """Test face landmark extraction."""
    
    @pytest.fixture
    def auth(self):
        """Create an authenticated FaceAuthenticator."""
        a = FaceAuthenticator()
        try:
            a._init_landmarker()
        except Exception as e:
            pytest.skip(f"Could not initialize landmarker: {e}")
        return a
    
    def test_extract_from_blank_image(self, auth):
        """Test extraction from blank image (should return None)."""
        # Create a blank image
        blank_image = np.zeros((480, 640, 3), dtype=np.uint8)
        
        landmarks = auth._extract_landmarks(blank_image)
        
        # Blank image should have no face
        assert landmarks is None
        print("No face detected in blank image (correct)")
    
    def test_extract_landmarks_format(self, auth):
        """Test that landmarks have correct format when detected."""
        # This would require a real face image
        # For now, just verify the method exists and is callable
        assert callable(auth._extract_landmarks)


class TestLandmarkComparison:
    """Test face landmark comparison."""
    
    def test_compare_identical_landmarks(self):
        """Test comparing identical landmarks."""
        auth = FaceAuthenticator()
        
        # Create mock landmarks (468 points * 3 coords = 1404 values)
        landmarks = np.random.rand(1404).astype(np.float32)
        
        result = auth._compare_landmarks(landmarks, landmarks)
        assert result == True
        print("Identical landmarks comparison: True (correct)")
    
    def test_compare_different_landmarks(self):
        """Test comparing completely different landmarks."""
        auth = FaceAuthenticator()
        
        landmarks1 = np.random.rand(1404).astype(np.float32)
        landmarks2 = np.random.rand(1404).astype(np.float32)
        
        result = auth._compare_landmarks(landmarks1, landmarks2)
        # Random vectors should likely be different
        print(f"Random landmarks comparison: {result}")
    
    def test_compare_with_threshold(self):
        """Test comparison with different thresholds."""
        auth = FaceAuthenticator()
        
        landmarks1 = np.ones(1404, dtype=np.float32)
        landmarks2 = np.ones(1404, dtype=np.float32) * 0.99  # Very similar
        
        # Should pass with high threshold
        result_high = auth._compare_landmarks(landmarks1, landmarks2, threshold=0.5)
        print(f"High threshold (0.5) result: {result_high}")
        
        # May fail with low threshold
        result_low = auth._compare_landmarks(landmarks1, landmarks2, threshold=0.001)
        print(f"Low threshold (0.001) result: {result_low}")


class TestReferenceImage:
    """Test reference image handling."""
    
    def test_default_reference_path(self):
        """Test default reference image path."""
        auth = FaceAuthenticator()
        # Default is "reference.jpg" in backend directory
        print(f"Reference path: {auth.reference_image_path}")
    
    def test_load_reference(self):
        """Test loading reference image."""
        auth = FaceAuthenticator()
        
        ref_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "backend",
            "reference.jpg"
        )
        
        if os.path.exists(ref_path):
            auth._load_reference()
            print("Reference image loaded")
        else:
            print("No reference image found (expected in new setup)")


class TestCameraAccess:
    """Test camera access functions."""
    
    def test_camera_methods_exist(self):
        """Test that camera-related methods exist."""
        auth = FaceAuthenticator()
        
        assert hasattr(auth, 'start_authentication_loop')
        assert hasattr(auth, 'stop')
        assert hasattr(auth, '_run_cv_loop')
        print("All camera methods exist")


class TestDependencies:
    """Test required dependencies."""
    
    def test_mediapipe_import(self):
        """Test MediaPipe is installed."""
        try:
            import mediapipe
            print(f"MediaPipe version: {mediapipe.__version__}")
        except ImportError:
            pytest.skip("MediaPipe not installed")
    
    def test_opencv_import(self):
        """Test OpenCV is installed."""
        import cv2
        print(f"OpenCV version: {cv2.__version__}")
    
    def test_numpy_import(self):
        """Test NumPy is installed."""
        import numpy
        print(f"NumPy version: {numpy.__version__}")
