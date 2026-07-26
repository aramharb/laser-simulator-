# Arena Size Debug Guide

This document explains how to debug arena size synchronization between the Angular frontend and Python backend.

## What to Look For in Browser Console

Open the browser DevTools (**F12** → **Console** tab) and look for these logs when testing:

### 1. **Arena Sync from Host**
When the component initializes or resizes:
```
[ExerciceComponent] Arena size synced from host: 800x600 → 1024x768
```
- **What it means**: The Pixi game container dimensions have changed
- **Expected**: Width and height should match your canvas/container size
- **Problem**: If missing or shows `0x0`, the container element isn't properly sized

### 2. **Calibration Starting**
When you click "Start Calibration":
```
[ExerciceComponent] Starting calibration with arena options: {
  debugPreview: true,
  calibrate: true,
  arenaWidth: 1024,
  arenaHeight: 768
}
[ShootOffSocket] Connecting with arena size: 1024 x 768
```
- **What it means**: The arena dimensions are being sent to the backend via query params
- **Expected**: `arenaWidth` and `arenaHeight` should match your container size
- **Problem**: If `arenaWidth: 0` or missing, check that `syncArenaSizeFromHost()` ran first

### 3. **Calibration Status Received**
During calibration:
```
[ExerciceComponent] Calibration status received: {
  status: "calibrating",
  elapsed_seconds: 2.5
}
```

When calibration completes:
```
[ExerciceComponent] Calibration status received: {
  status: "calibrated",
  bbox: [150, 100, 850, 700],
  mode: "auto",
  confidence: 0.87,
  elapsed_seconds: 3.2,
  arena_w: 1024,
  arena_h: 768
}
[ExerciceComponent] Arena width updated from server: 1024 → 1024
[ExerciceComponent] Arena height updated from server: 768 → 768
```
- **What it means**: Backend acknowledges the arena dimensions and confirms them
- **Expected**: `arena_w` and `arena_h` in response should match what you sent
- **Problem**: If missing or different, backend didn't receive the query params correctly

### 4. **Shot Stream Starting**
When a game session starts:
```
[ExerciceComponent] Starting shot stream with arena size: {width: 1024, height: 768}
```
- **What it means**: Shot detection stream is active with current arena dimensions
- **Expected**: Width and height should be your container size
- **Problem**: If dimensions changed since calibration, shots will be misaligned

### 5. **Shots Being Received**
When you take a shot:
```
[ExerciceComponent] Shot received - Arena: 1024x768, Shot coords: (512.45, 384.67)
```
- **What it means**: A shot event arrived with raw arena coordinates
- **Expected**: Coordinates should be within your arena bounds (0 to 1024, 0 to 768)
- **Problem**: If outside bounds, check calibration bounding box

### 6. **Shots Mapped to World**
```
[ExerciceComponent] Shot mapped to world coords: (512.34, 384.56)
```
- **What it means**: Raw arena coords converted to game world coordinates
- **Expected**: Should be within your actual canvas bounds
- **Problem**: If way off, arena size mismatch between frontend and backend

## Complete Flow Example

Here's what a successful calibration → shot flow looks like in the console:

```
[ExerciceComponent] Arena size synced from host: 800x600 → 1024x768
[ExerciceComponent] Starting calibration with arena options: {debugPreview: true, calibrate: true, arenaWidth: 1024, arenaHeight: 768}
[ShootOffSocket] Connecting with arena size: 1024 x 768 {arenaWidth: 1024, arenaHeight: 768, url: "ws://localhost:4200/api/ws/shots?calibrate=1&debug=1&arena_w=1024&arena_h=768"}
[ExerciceComponent] Calibration status received: {status: "calibrating", elapsed_seconds: 0.5}
[ExerciceComponent] Calibration status received: {status: "calibrated", bbox: [150, 100, 850, 700], mode: "auto", confidence: 0.87, elapsed_seconds: 3.2, arena_w: 1024, arena_h: 768}
[ExerciceComponent] Arena width updated from server: 1024 → 1024
[ExerciceComponent] Arena height updated from server: 768 → 768
[ExerciceComponent] Starting shot stream with arena size: {width: 1024, height: 768}
[ExerciceComponent] Shot received - Arena: 1024x768, Shot coords: (512.45, 384.67)
[ExerciceComponent] Shot mapped to world coords: (512.34, 384.56)
```

## Common Issues & Solutions

### Issue: Arena dimensions are 0x0
**Solution:**
- Check that the Pixi game container element has CSS dimensions set
- Verify `getBoundingClientRect()` is called after layout has settled
- Check if the host element is visible and has a size

### Issue: Backend receives different arena size than sent
**Solution:**
- Check the WebSocket URL in the console for correct `arena_w` and `arena_h` params
- Verify backend is reading query params correctly
- Look at backend logs to see what it received

### Issue: Shots appear offset
**Solution:**
1. Compare sent vs received arena sizes in console
2. If different, shots will be linearly scaled wrong
3. Restart the game with correct container size before calibrating
4. Ensure container size doesn't change during game

### Issue: No shot mapping logs
**Solution:**
- Check if shot stream started successfully
- Verify shots are actually being detected by backend
- Look for shot stream errors in console

## Checking Backend Logs

In the Python terminal running `api.py`, look for:

```
SHOT_DEBUG candidates=3 clusters=2 shots=1 ...
```

And in browser console, match the timestamp with the shot coordinates.

## Testing Steps

1. Open browser DevTools (F12)
2. Go to Console tab
3. Start the Angular app
4. Click "Start Calibration"
5. Watch console for arena sync and calibration messages
6. Verify `arena_w` and `arena_h` in response match what was sent
7. Start a game session
8. Take a shot and watch mapping logs
9. Compare arena dimensions throughout the flow

All arena size values should be **consistent** from initial host sync → calibration send → backend response → shot mapping.
