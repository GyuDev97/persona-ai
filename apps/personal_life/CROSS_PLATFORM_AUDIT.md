# GYUVIS cross-platform audit

Static audit completed 2026-09-30. `.env` and `.env.*` files were excluded;
only environment-variable names referenced by source code were reviewed.

## Runtime findings

| Files | Purpose | macOS risk | Action |
| --- | --- | --- | --- |
| `startup_jarvis_stack.bat`, `startup_python.bat`, sensor/posture `.bat` launchers | Legacy Windows startup | Hard-coded `D:\`, `venv\Scripts`, `cmd`, PowerShell, `start` | Retained for compatibility; replaced as the recommended path by `scripts/start.py`, `status.py`, and `stop.py`. |
| `app/services/desktop_action_service.py` | Open browser, files, Notepad, Calculator | `os.startfile`, `.exe` app names and Chrome paths | Uses `platform_service`: `open`, default browser, TextEdit/Calculator on macOS. |
| `app/services/jarvis_hud_service.py` | Launch browser HUD | Windows browser locations and `os.startfile` | Uses cross-platform browser candidates/default-browser fallback. |
| `posture_alert/camera.py`, `home_arrival_sensor/camera.py` | Webcam capture | DirectShow is Windows-specific | Selects DirectShow on Windows and AVFoundation on macOS. Camera index remains environment-configurable. |
| `posture_alert/screen_alert.py` | Warning overlay | Click-through/multi-monitor depends on `ctypes.windll` | Existing Windows behavior remains. macOS is deliberately limited to a best-effort Tk overlay and failures are non-fatal. |
| `app/services/gyuvis_tts_service.py`, `pc_wake_listener.py` | Edge TTS/local fallback | PowerShell speech only exists on Windows | Edge TTS remains default. macOS uses `say` when fallback is enabled; Windows retains PowerShell fallback. |
| `pc_desktop_actions.py`, `naver_blog_writer.py` | Move browser/Excel windows and automate existing Edge | pywin32, pywinauto, COM, `cmd start`, `ctypes.windll` | Windows-only capability; not loaded by Core startup. macOS falls back to normal browser/file actions but cannot move another app window or automate Excel COM. |
| `desktop_context_overlay.py` | Local desktop overlay | Taskbar/window styling uses Win32 calls | Win32 calls are already guarded. Base Tk overlay remains best effort; Core does not depend on it. |
| `company-ai/app/*.py`, `pc_agent_runner.py` | Child process and Git/Codex workflows | `shell=True` in the generic build runner may require a shell-compatible command | No Windows shell command is hard-coded. Keep commands as explicit executable/argument arrays where possible; this is a follow-up hardening item, not a Core startup blocker. |

## Non-runtime findings

`build_*`, `caption_*`, and other video/thumbnail utilities contain personal
Windows paths and Windows font names. They are production-media helpers rather
than GyuNexus/GYUVIS runtime code. Their path configuration should be moved to
arguments or a separate media-tool configuration before those utilities are
advertised as cross-platform.

Documentation that referenced `D:\...` or direct `.bat` execution was updated
for the posture and entrance-sensor paths. Historical handoff/video documents
retain their original Windows-specific evidence and are not startup inputs.

## Dependency assessment

| Dependency | Status |
| --- | --- |
| `pywinauto` / pywin32 feature set | Windows-only optional integration; `pywinauto` now has a Windows environment marker. |
| OpenCV | Cross-platform; current packages publish macOS ARM64 wheels. |
| MediaPipe 0.10.18 | Cross-platform for the supported Python versions, including a macOS universal2 wheel. Kept pinned to avoid changing posture behavior. |
| InsightFace | Python package is platform-neutral, but relies on local OpenCV/ONNX Runtime installation. |
| ONNX Runtime | Cross-platform; current packages publish macOS ARM64 wheels. CPU is the supported default on Apple Silicon. |
| NumPy / pygame / Edge TTS | Cross-platform; audio device permissions/output remain host-specific. |
| `psutil` | Added for portable port/process status and controlled shutdown. |

## Verification matrix

- Windows 11 x86_64: Core, DirectShow camera, Windows overlay and native
  fallback retain their existing behavior.
- macOS Apple Silicon: Core, SQLite/MariaDB configuration, browser HUD, camera
  capture, posture monitor, entrance sensor, Edge TTS and `say` fallback are
  supported through the same Python modules.
- Optional integrations use capability detection at `/system/environment`; a
  missing dependency, camera permission, or unsupported overlay does not block
  Core startup.
