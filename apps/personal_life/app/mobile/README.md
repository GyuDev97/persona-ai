# Gyuvis Mobile

Flutter mobile client for the Personal Life Assistant.

## What It Does

- Connects to the local Personal Life Assistant API.
- Sends text and voice commands to `/mobile/assistant/command`.
- Polls PC agent task status through `/agent/tasks/{id}`.
- Supports Korean speech recognition, TTS replies, and clap wake mode.

## Run

```powershell
flutter run
```

The default server URL is defined in `lib/config/app_config.dart`.

To override it at launch:

```powershell
flutter run --dart-define=GYUVIS_SERVER_URL=http://192.168.0.19:8000
```

The in-app command sheet also lets you edit the server URL without rebuilding.

## Structure

- `lib/main.dart`: app state, voice flow, and main screen.
- `lib/config/`: app-level defaults.
- `lib/models/`: small UI/domain models.
- `lib/services/`: API client and text formatting helpers.
- `lib/widgets/`: reusable UI widgets.
