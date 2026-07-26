ShootOFF - Modernized Game Environment
======================================
Here’s the updated workflow and setup guide, reflecting the migration to the Angular Application Builder and the integration of PixiJS for the game rendering engine.

**Workflow (data flow)**
- The Python backend opens the webcam, runs calibration, then emits WebSocket messages at `ws://<host>:8000/ws/shots` with either `{status: "calibrating"}`, `{status: "calibrated", bbox: [...]}`, or `{event: "shot", x, y, timestamp}` from api.py.
- The Angular app connects to that WebSocket using `ShootOffSocketService` and consumes those messages from shootoff-socket.service.ts.
- The UI is routed to `/exercice` only, so you must open that path from app.routes.ts.

**How to run (exact steps, Windows PowerShell)**

1) **Start the backend (FastAPI + webcam)**
```powershell
cd "C:\Users\aram\OneDrive\Bureau\aydi_vfinal22\ShootOFF-legacy-master"
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python api.py
```
- This starts the WebSocket server at `ws://localhost:8000/ws/shots`.
- If there is no webcam or it is not accessible, the backend sends `{ "error": "Webcam not found" }`.

2) **Start the frontend (Angular)**
```powershell
cd "C:\Users\aram\OneDrive\Bureau\aydi_vfinal22\angular - Copy"
npm install
npm start
```
- Open the app at: `http://localhost:4200/exercice`
- The base route `/` shows only the router outlet and will appear blank.

**How to use the app**
- Wait for calibration to complete (the backend sends `status: "calibrated"` when it finds the projector/arena bounding box).
- Click **Start** in the UI.
- Shine the laser in the camera’s view; the backend emits `{event:"shot"}`, and the game should register shots.

**Project Updates**
- **Rendering Engine**: Integrated PixiJS for high-performance sprite animations and mesh deformations (utilizing `AnimatedSprite` and `MeshPlane` for realistic surface mapping).
- **Build System**: Migrated to the new Angular `@angular/build:application` (Vite/esbuild engine). 
  * Note: Production builds now output to the `dist/browser` directory.
  * Redundant targets (Server, Prerender, AppShell) have been removed in favor of the unified application builder.

**How to test**
1) **Build test**
```powershell
npm run build
```

2) **Unit tests**
```powershell
npm test
```

3) **Manual WebSocket verification (browser DevTools)**
- Open DevTools → Network → WS.
- Select the connection to `ws://localhost:8000/ws/shots`.
- You should see messages like:
```json
{"status":"calibrating"}
{"status":"calibrated","bbox":[...]}
{"event":"shot","x":123.45,"y":456.78,"timestamp":...}
```

If you want, I can add a small on-screen log panel in the Angular UI to show these messages without using DevTools.