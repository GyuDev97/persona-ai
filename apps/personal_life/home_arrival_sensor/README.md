# GYUVIS 귀가 감지 센서 (A 노트북)

This is a local-only webcam PoC. It sends only an authenticated arrival event
to GyuNexus Core; photos, video, and embeddings never leave this laptop.

## A-laptop setup

1. Clone or pull this repository on A.
2. Create `home_arrival_sensor/.env` from `.env.example`.
3. Set `API_URL` to B's LAN address and copy the same token used by B.
4. Install dependencies with the active virtual-environment Python:

   ```bash
   python -m pip install -r home_arrival_sensor/requirements.txt
   ```

5. Put 3-10 owner-only photos in `home_arrival_sensor/data/owner_images/`.
   Use clear, varied lighting; do not include anyone else.
6. Create the embedding locally:

   ```bash
   python -m home_arrival_sensor.enroll
   ```

7. Start with `python -m home_arrival_sensor.main`.

If A cannot reach B, confirm B's Windows Firewall allows inbound TCP port 8000
on the private LAN. The Core launcher already listens on `0.0.0.0:8000`.

The first InsightFace run may download its model to A's local user cache.
Inference then runs locally. No cloud face-recognition API is used.

## macOS Apple Silicon

Use the same commands after creating and activating a `.venv` with `python3`.
The shared camera adapter selects AVFoundation on macOS; grant Camera access to
the terminal or Python IDE in System Settings → Privacy & Security → Camera.
Start with `FACE_PROVIDER=cpu`; `CUDAExecutionProvider` is Windows/NVIDIA
specific and is not the macOS default. If a wheel cannot be installed for the
chosen Python release, the Core server still runs and `/system/environment`
reports the entrance sensor as unavailable rather than failing server startup.

## Tuning

- `FACE_MATCH_THRESHOLD`: higher is stricter. Start at `0.45`.
- `REQUIRED_MATCH_FRAMES`: start at `4`.
- `FRAME_SKIP`: higher reduces CPU use; start at `3`.
- `CAMERA_INDEX`: change to `1` if an external USB webcam is not detected.

Use CPU first on the i5-8265U. The MX450 is optional: install
`onnxruntime-gpu` in place of `onnxruntime`, set `FACE_PROVIDER=gpu`, and test
the camera flow again.
