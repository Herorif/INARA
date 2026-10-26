# Manual tools

Developer utilities run by hand. They are not part of the runtime, CI or packaging.

- `capture_face.py` — opens the webcam and saves the face-authentication reference image to `backend/reference.jpg` (needs `opencv-python`).
- `verify_cad.py` — asks the legacy `CadAgent` for a sample prototype using the configured provider key (live API call).
- `verify_iteration_mock.py` — exercises `CadAgent` prototype iteration with mocked provider/runtime modules (no API call).
