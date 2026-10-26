"""
Tests for Face Authentication.

Three groups, each with its own narrow skip:
- logic tests load ``authenticator`` against fake mediapipe/cv2 (and a stub numpy
  when numpy is absent), so they run everywhere with no camera, model or network;
- landmark-math tests need real numpy;
- real-stack tests need numpy, OpenCV, MediaPipe and the installed face model.
"""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

AUTH_SOURCE = Path(__file__).resolve().parent.parent / "backend" / "authenticator.py"
HAS_NUMPY = importlib.util.find_spec("numpy") is not None
REAL_STACK_MISSING = [name for name in ("numpy", "cv2", "mediapipe")
                      if importlib.util.find_spec(name) is None]
REAL_MODEL_PATH = AUTH_SOURCE.parent / "face_landmarker.task"

needs_numpy = pytest.mark.skipif(not HAS_NUMPY, reason="numpy not installed (landmark math needs real arrays)")


class FakeCapture:
    def __init__(self, index, _backend, opened):
        self.index, self.opened, self.released = index, opened, False

    def isOpened(self):
        return self.opened

    def read(self):
        return False, None

    def release(self):
        self.released = True


class FakeLandmarker:
    def __init__(self, faces=()):
        self.faces = list(faces)
        self.images = []

    def detect(self, image):
        self.images.append(image)
        return types.SimpleNamespace(face_landmarks=self.faces)


def fake_modules(created, opened_cameras):
    """Minimal mediapipe and cv2 surfaces that authenticator.py touches."""
    mp = types.ModuleType("mediapipe")
    mp.ImageFormat = types.SimpleNamespace(SRGB="srgb")
    mp.Image = lambda image_format, data: types.SimpleNamespace(format=image_format, data=data)
    tasks = types.ModuleType("mediapipe.tasks")
    python = types.ModuleType("mediapipe.tasks.python")
    python.BaseOptions = lambda model_asset_path: types.SimpleNamespace(model_asset_path=model_asset_path)
    vision = types.ModuleType("mediapipe.tasks.python.vision")
    vision.FaceLandmarkerOptions = lambda **kwargs: types.SimpleNamespace(**kwargs)

    def create_from_options(options):
        created.append(options)
        return FakeLandmarker()

    vision.FaceLandmarker = types.SimpleNamespace(create_from_options=create_from_options)
    mp.tasks, tasks.python, python.vision = tasks, python, vision

    cv2 = types.ModuleType("cv2")
    cv2.CAP_DSHOW, cv2.CAP_ANY = 700, 0
    cv2.captures = []

    def video_capture(index, backend):
        capture = FakeCapture(index, backend, opened=index in opened_cameras)
        cv2.captures.append(capture)
        return capture

    cv2.VideoCapture = video_capture
    modules = {"mediapipe": mp, "mediapipe.tasks": tasks, "mediapipe.tasks.python": python,
               "mediapipe.tasks.python.vision": vision, "cv2": cv2}
    if not HAS_NUMPY:
        modules["numpy"] = types.ModuleType("numpy")  # unused by the logic tests
    return modules


@pytest.fixture
def fake_auth(monkeypatch, tmp_path):
    """Load authenticator.py against fakes, with the model path pointed at tmp_path."""
    created = []
    modules = fake_modules(created, opened_cameras=set())
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("authenticator_under_test", AUTH_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = tmp_path / "face_landmarker.task"
    model.write_bytes(b"model")
    monkeypatch.setattr(module.FaceAuthenticator, "MODEL_PATH", str(model))

    def no_download(*_args, **_kwargs):
        raise AssertionError("tests must never download the face model")

    monkeypatch.setattr(module.urllib.request, "urlretrieve", no_download)
    module.created_landmarkers, module.cv2 = created, modules["cv2"]
    return module


class TestModelHandling:
    def test_model_url_is_the_official_https_landmarker(self, fake_auth):
        url = fake_auth.FaceAuthenticator.MODEL_URL
        assert url.startswith("https://storage.googleapis.com/mediapipe-models/face_landmarker/")
        assert url.endswith("/face_landmarker.task")

    def test_default_model_path_is_next_to_the_module(self, monkeypatch):
        # Load a second copy without the fixture's MODEL_PATH override.
        for name, module in fake_modules([], set()).items():
            monkeypatch.setitem(sys.modules, name, module)
        spec = importlib.util.spec_from_file_location("authenticator_default_path", AUTH_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert Path(module.FaceAuthenticator.MODEL_PATH) == REAL_MODEL_PATH

    def test_refuses_to_start_without_installed_model(self, fake_auth, tmp_path, monkeypatch):
        monkeypatch.setattr(fake_auth.FaceAuthenticator, "MODEL_PATH", str(tmp_path / "missing.task"))
        with pytest.raises(RuntimeError, match="Install the face model"):
            fake_auth.FaceAuthenticator(reference_image_path=str(tmp_path / "ref.jpg"))
        assert fake_auth.created_landmarkers == []

    def test_installed_model_initializes_landmarker(self, fake_auth, tmp_path):
        statuses, frames = [], []

        async def on_status(value):
            statuses.append(value)

        async def on_frame(value):
            frames.append(value)

        auth = fake_auth.FaceAuthenticator(reference_image_path=str(tmp_path / "ref.jpg"),
                                           on_status_change=on_status, on_frame=on_frame)

        options, = fake_auth.created_landmarkers
        assert options.base_options.model_asset_path == fake_auth.FaceAuthenticator.MODEL_PATH
        assert options.num_faces == 1
        assert auth.landmarker is not None
        assert auth.on_status_change is on_status and auth.on_frame is on_frame
        assert auth.reference_landmarks is None  # reference file absent
        assert auth.authenticated is False and auth.running is False


class TestAuthenticationLoop:
    @pytest.fixture
    def auth(self, fake_auth, tmp_path):
        return fake_auth.FaceAuthenticator(reference_image_path=str(tmp_path / "ref.jpg"))

    async def test_loop_without_reference_never_opens_camera(self, auth, fake_auth):
        await auth.start_authentication_loop()
        assert auth.running is False
        assert fake_auth.cv2.captures == []

    async def test_already_authenticated_reports_true_without_camera(self, auth, fake_auth):
        statuses = []

        async def on_status(value):
            statuses.append(value)

        auth.on_status_change, auth.authenticated = on_status, True
        await auth.start_authentication_loop()
        assert statuses == [True]
        assert fake_auth.cv2.captures == []

    def test_cv_loop_tries_both_cameras_then_stops(self, auth, fake_auth):
        auth.running = True
        auth._run_cv_loop(asyncio.new_event_loop())
        assert [capture.index for capture in fake_auth.cv2.captures] == [0, 1]
        assert auth.running is False
        assert auth.authenticated is False

    def test_stop_clears_running(self, auth):
        auth.running = True
        auth.stop()
        assert auth.running is False

    def test_no_landmarker_means_no_landmarks(self, auth):
        auth.landmarker = None
        assert auth._extract_landmarks(object()) is None

    def test_missing_landmarks_never_match(self, auth):
        assert auth._compare_landmarks(None, None) is False


@needs_numpy
class TestLandmarkMath:
    @pytest.fixture
    def auth(self, fake_auth, tmp_path):
        return fake_auth.FaceAuthenticator(reference_image_path=str(tmp_path / "ref.jpg"))

    def test_identical_landmarks_match(self, auth):
        import numpy as np
        landmarks = np.linspace(0.1, 1.0, 1404, dtype=np.float32)
        assert bool(auth._compare_landmarks(landmarks, landmarks)) is True

    def test_orthogonal_landmarks_do_not_match(self, auth):
        import numpy as np
        a = np.zeros(1404, dtype=np.float32)
        b = np.zeros(1404, dtype=np.float32)
        a[0], b[1] = 1.0, 1.0
        assert not auth._compare_landmarks(a, b)

    def test_zero_vector_never_matches(self, auth):
        import numpy as np
        assert auth._compare_landmarks(np.zeros(3), np.ones(3)) is False

    def test_threshold_controls_the_match(self, auth):
        import numpy as np
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([1.0, 0.3, 0.0])  # cosine similarity ~0.958
        assert auth._compare_landmarks(a, b, threshold=0.1)
        assert not auth._compare_landmarks(a, b, threshold=0.01)

    def test_extracts_flattened_landmarks_from_detected_face(self, auth):
        import numpy as np
        point = types.SimpleNamespace
        auth.landmarker.faces = [[point(x=0.1, y=0.2, z=0.3), point(x=0.4, y=0.5, z=0.6)]]
        landmarks = auth._extract_landmarks(np.zeros((4, 4, 3), dtype=np.uint8))
        assert landmarks.shape == (6,)
        assert np.allclose(landmarks, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6])

    def test_no_face_detected_returns_none(self, auth):
        import numpy as np
        assert auth._extract_landmarks(np.zeros((4, 4, 3), dtype=np.uint8)) is None


@pytest.mark.skipif(bool(REAL_STACK_MISSING),
                    reason=f"face auth stack not installed: missing {', '.join(REAL_STACK_MISSING)}")
@pytest.mark.skipif(not REAL_MODEL_PATH.exists(),
                    reason=f"face model not installed at {REAL_MODEL_PATH}")
class TestRealFaceModel:
    """Real MediaPipe landmarker on the installed model; no camera, no network."""

    def test_blank_image_has_no_face(self, tmp_path):
        import numpy as np
        from authenticator import FaceAuthenticator
        auth = FaceAuthenticator(reference_image_path=str(tmp_path / "ref.jpg"))
        assert auth.landmarker is not None
        assert auth._extract_landmarks(np.zeros((480, 640, 3), dtype=np.uint8)) is None
