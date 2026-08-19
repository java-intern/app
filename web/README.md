# AdaptiveTrust Web-Based Administration & Simulation Portal

This is a premium, lightweight, single-page application (SPA) built using modern Vanilla HTML5, CSS3, and JavaScript. It replicates the zero-trust administration controls and employee dashboard interfaces of the AdaptiveTrust multi-tenant platform.

## Features Included
1. **Authentication Portal:** Toggle between user login, admin workspace creation, and employee invite codes.
2. **Admin Command Center:** Displays aggregate corporate trust metrics, dynamically sorts/filters the user directory, monitors real-time telemetry updates via a custom Server-Sent Events (SSE) log terminal, and launches override popups (Boost Trust, Force MFA, Suspend Account).
3. **Employee Self-Service Profile:** Displays a glassmorphic user trust dashboard with an animated radial score gauge, event audit timeline, and an interactive **Telemetry Simulator** to mock coordinates and device states.

---

## How to Host Locally

Since it consists of pure static files (`index.html`, `styles.css`, and `app.js`), you can host it locally using any static web server:

### Option A: Python HTTP Server (Built-in)
Run the following command inside the `web-frontend/` directory:
```bash
python -m http.server 3000
```
Then navigate to: `http://localhost:3000`

### Option B: Node.js static hosting
Install and run `serve` globally:
```bash
npm install -g serve
serve -p 3000
```
Then navigate to: `http://localhost:3000`

---

## API Configuration

By default, the client requests are routed to the FastAPI backend gateway running at:
`http://localhost:8000/api/v1`

If you are hosting your backend at a different address, modify the `API_BASE` variable at the top of [app.js](file:///C:/Users/yogan/.gemini/antigravity-ide/scratch/adaptivetrust-multitenant/web-frontend/app.js):
```javascript
const API_BASE = 'http://YOUR_BACKEND_IP:PORT/api/v1';
```
