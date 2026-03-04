from __future__ import annotations

import asyncio
import json
import time
import webbrowser
from dataclasses import dataclass, field


@dataclass
class UiState:
    last_payload: dict | None = None
    clients: set = field(default_factory=set)

    async def broadcast(self, payload: dict) -> None:
        self.last_payload = payload
        if not self.clients:
            return
        message = json.dumps(payload, ensure_ascii=False)
        dead: list = []
        for ws in list(self.clients):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


def _html() -> str:
    # Minimal single-file UI (kept dependency-free on the frontend).
    return """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>ATeameI</title>
    <style>
      :root {
        color-scheme: dark;
        --bg: #0b1020;
        --panel: #121a33;
        --muted: #a7b0d6;
        --text: #e7ecff;
        --accent: #7aa2ff;
        --accent2: #d07cff;
        --border: rgba(255,255,255,.08);
        --shadow: rgba(0,0,0,.35);
      }
      body {
        margin: 0;
        background: radial-gradient(1200px 800px at 20% 0%, #17224a, var(--bg));
        color: var(--text);
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji";
      }
      header {
        padding: 16px 20px;
        border-bottom: 1px solid var(--border);
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
      }
      .brand {
        display: flex;
        gap: 10px;
        align-items: baseline;
      }
      .brand h1 {
        margin: 0;
        font-size: 18px;
        letter-spacing: 0.2px;
      }
      .pill {
        font-size: 12px;
        color: var(--muted);
        border: 1px solid var(--border);
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(255,255,255,.03);
      }
      .grid {
        display: grid;
        grid-template-columns: 2fr 1fr;
        gap: 16px;
        padding: 16px;
      }
      .panel {
        background: linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.02));
        border: 1px solid var(--border);
        border-radius: 14px;
        box-shadow: 0 10px 30px var(--shadow);
        overflow: hidden;
      }
      .panel h2 {
        margin: 0;
        padding: 12px 14px;
        font-size: 13px;
        color: var(--muted);
        border-bottom: 1px solid var(--border);
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      .panel .body {
        padding: 14px;
        max-height: calc(100vh - 160px);
        overflow: auto;
        white-space: pre-wrap;
        line-height: 1.35;
      }
      .suggestion {
        font-size: 14px;
        border-left: 3px solid var(--accent2);
        padding-left: 12px;
      }
      .transcript-line {
        margin: 0 0 10px 0;
        padding: 10px 12px;
        border: 1px solid rgba(255,255,255,.06);
        border-radius: 12px;
        background: rgba(0,0,0,.12);
      }
      .ts {
        color: var(--muted);
        font-size: 11px;
        margin-bottom: 5px;
      }
      footer {
        padding: 12px 16px;
        color: var(--muted);
        border-top: 1px solid var(--border);
        display: flex;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
      }
      a { color: var(--accent); text-decoration: none; }
      code { color: #cfe0ff; }
    </style>
  </head>
  <body>
    <header>
      <div class="brand">
        <h1>ATeameI</h1>
        <span class="pill" id="status">(connecting…)</span>
      </div>
      <div class="pill">Suggestions only • Use with consent</div>
    </header>

    <div class="grid">
      <section class="panel">
        <h2>Live transcript <span class="pill" id="lines">0 lines</span></h2>
        <div class="body" id="transcript"></div>
      </section>
      <section class="panel">
        <h2>Suggested reply</h2>
        <div class="body suggestion" id="suggestion">(waiting…)</div>
      </section>
    </div>

    <footer>
      <div>Tip: keep <code>--chunk-seconds 1</code> for faster turns; pick a smaller Whisper model for lower latency.</div>
      <div><a href="#" onclick="location.reload(); return false;">Reload</a></div>
    </footer>

    <script>
      const statusEl = document.getElementById("status");
      const suggestionEl = document.getElementById("suggestion");
      const transcriptEl = document.getElementById("transcript");
      const linesEl = document.getElementById("lines");

      function fmtTime(ts) {
        try {
          const d = new Date(ts * 1000);
          return d.toLocaleTimeString();
        } catch {
          return "";
        }
      }

      function render(payload) {
        statusEl.textContent = payload.status || "(no status)";
        suggestionEl.textContent = payload.suggestion || "—";

        const lines = payload.transcript || [];
        linesEl.textContent = `${lines.length} lines`;

        transcriptEl.replaceChildren();
        for (const l of lines) {
          const t = typeof l.t === "number" ? fmtTime(l.t) : "";
          const text = (l.text || "").toString();

          const wrap = document.createElement("div");
          wrap.className = "transcript-line";

          const ts = document.createElement("div");
          ts.className = "ts";
          ts.textContent = t;

          const body = document.createElement("div");
          body.textContent = text;

          wrap.append(ts, body);
          transcriptEl.append(wrap);
        }

        // keep scrolled to bottom
        transcriptEl.scrollTop = transcriptEl.scrollHeight;
      }

      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => { statusEl.textContent = "connected"; };
      ws.onclose = () => { statusEl.textContent = "disconnected"; };
      ws.onerror = () => { statusEl.textContent = "error"; };
      ws.onmessage = (ev) => {
        try {
          render(JSON.parse(ev.data));
        } catch {
          // ignore
        }
      };
    </script>
  </body>
</html>
""".strip()


async def serve(
    *,
    state: UiState,
    port: int,
    open_browser: bool,
    run_task: asyncio.Task | None,
) -> int:
    try:
        from fastapi import FastAPI, WebSocket
        from fastapi.responses import HTMLResponse
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Missing UI dependencies. Run: pip install -r requirements.txt") from exc

    app = FastAPI()

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(_html())

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        state.clients.add(ws)
        try:
            if state.last_payload is not None:
                await ws.send_text(json.dumps(state.last_payload, ensure_ascii=False))
            while True:
                # Keep the connection alive; we don't expect client -> server messages.
                await ws.receive_text()
        except Exception:
            pass
        finally:
            state.clients.discard(ws)

    config = uvicorn.Config(app, host="127.0.0.1", port=int(port), log_level="warning")
    server = uvicorn.Server(config)

    async def _open() -> None:
        # Give the server a beat to bind.
        await asyncio.sleep(0.5)
        url = f"http://127.0.0.1:{port}/"
        if open_browser:
            webbrowser.open(url)

    open_task = asyncio.create_task(_open())
    server_task = asyncio.create_task(server.serve())

    # If we were given a runner task, we should stop the server when it ends.
    tasks = [server_task, open_task]
    if run_task is not None:
        tasks.append(run_task)

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # If the runner exits, request server shutdown.
        if run_task is not None and run_task in done and not server.should_exit:
            server.should_exit = True
        # Wait a tiny bit for a clean shutdown.
        await asyncio.sleep(0.25)
        for t in pending:
            t.cancel()
        return 0
    finally:
        # Best-effort shutdown
        server.should_exit = True


async def run_ui_with_runner(
    *,
    runner_coro,
    port: int,
    open_browser: bool,
) -> int:
    # Convenience helper: run the runner and the UI server together.
    state = UiState()
    runner_task = asyncio.create_task(runner_coro(state))
    return await serve(state=state, port=port, open_browser=open_browser, run_task=runner_task)
