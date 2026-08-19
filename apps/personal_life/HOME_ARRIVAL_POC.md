# Home-arrival PoC: Core PC verification

This first step verifies only the B laptop (GyuNexus Core). It accepts an
authenticated event, records it, wakes GYUVIS, and speaks a local greeting.
The A-laptop camera program is intentionally not included yet.

## 1. Configure B's `.env`

Keep the token private and use the identical value later in A's local `.env`:

```env
GYUVIS_HOME_ARRIVAL_API_TOKEN=replace_with_a_long_random_token
GYUVIS_HOME_ARRIVAL_COOLDOWN_SECONDS=600
GYUVIS_HOME_ARRIVAL_GREETING=어서 오세요.
# Optional: omit to reuse GYUVIS_TTS_BACKEND=edge
# GYUVIS_HOME_ARRIVAL_TTS_BACKEND=edge
```

The arrival event reuses the existing Edge TTS voice, rate, pitch, and fallback
settings. It receives only the greeting text; it never receives face images or
video.

## 2. Start the Core server

Run `startup_python.bat`. It listens on port 8000.

## 3. Send one test event from B

In PowerShell, replace the token with the value in B's `.env`:

```powershell
$body = @{ source = 'entrance_camera'; event = 'home_arrival'; person = 'owner'; confidence = 0.94; timestamp = (Get-Date).ToString('o') } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/events/home-arrival' -Headers @{ 'X-API-Token' = 'jsadhnjkdfviojsd892389324ujiwerhjsdfu' } -ContentType 'application/json' -Body $body
```
```
curl.exe -X POST "http://127.0.0.1:8000/api/events/home-arrival" -H "Content-Type: application/json" -H "X-API-Token: jsadhnjkdfviojsd892389324ujiwerhjsdfu" -d "{\"source\":\"entrance_camera\", \"event\":\"home_arrival\",\"person\":\"owner\",\"confidence\":0.94,\"timestamp\":\"2026-08-19T20:00:00+09:00\"}"
```

Expected result: `accepted=True`, GYUVIS HUD opens directly without waiting for
a finger gesture, and the Core PC says
"어서 오세요." A second request within the cooldown returns `duplicate=True`
and does not wake or speak again.

Each accepted event is stored in `home_arrival_events` with the sensor
timestamp, confidence, final result, HUD wake status, and TTS status. Only the
event metadata is stored; no image or video field exists in this API.
