"""Local browser UI for millet recording and settings.

The server is intentionally dependency-free: it uses the stdlib HTTP server,
serves a compact single-page app, and calls the same capture/transcribe helpers
as the CLI/GTK surfaces.
"""
from __future__ import annotations

import json
import mimetypes
import os
import queue
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from millet.capture import DRAIN_SECONDS
from millet.cli._helpers import _generate_pdf, _generate_summary
from millet.paths import apply_model_cache_environment, load_project_env, project_root, recordings_dir
from millet.utils import fmt_elapsed, fmt_size


ENV_FIELDS = [
    "HF_TOKEN",
    "MILLET_MODEL_CACHE_DIR",
    "MILLET_RECORDINGS_DIR",
    "MILLET_LANGUAGE",
    "MILLET_SUMMARY_PRESET",
    "MILLET_SUMMARY_BACKEND",
    "MILLET_SUMMARY_MODEL",
    "MILLET_OPENAI_BASE_URL",
    "MILLET_OPENAI_API_KEY",
    "MILLET_OLLAMA_SINGLEPASS",
]

OPTION_DEFAULTS = {
    "model": "large-v3-turbo",
    "device": "auto",
    "torch_device": "auto",
    "asr_backend": "auto",
    "mlx_model": "",
    "compute_type": "float16",
    "batch_size": "16",
    "language": "auto",
    "min_speakers": "",
    "max_speakers": "",
    "virtual_sink": "0",
    "mic": "",
    "monitor": "",
    "summarize": "1",
    "summary_preset": "",
    "summary_backend": "",
    "summary_model": "",
    "ollama_singlepass": "0",
    "skip_alignment": "0",
    "mixdown": "dual-diarize",
}

OPTION_ENV_PREFIX = "MILLET_WEBUI_"


def _env_path() -> Path:
    return project_root() / ".env"


def _parse_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _none_if_auto(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value or value == "auto":
        return None
    return value


def _none_if_empty(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _parse_env_file(path: Path | None = None) -> dict[str, str]:
    path = path or _env_path()
    if not path.exists():
        return {}

    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            result[key] = _unquote_env_value(value.strip())
    return result


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _quote_env_value(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    if any(ch.isspace() for ch in text) or "#" in text or '"' in text:
        return json.dumps(text, ensure_ascii=False)
    return text


def _write_env_values(values: dict[str, str], path: Path | None = None) -> Path:
    path = path or _env_path()
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(values)
    out: list[str] = []

    for raw_line in existing:
        stripped = raw_line.strip()
        candidate = stripped
        prefix = ""
        if candidate.startswith("export "):
            prefix = "export "
            candidate = candidate[len("export ") :].lstrip()
        if "=" in candidate and not candidate.startswith("#"):
            key = candidate.split("=", 1)[0].strip()
            if key in pending:
                out.append(f"{prefix}{key}={_quote_env_value(pending.pop(key))}")
                continue
        out.append(raw_line)

    if pending:
        if out and out[-1].strip():
            out.append("")
        for key in sorted(pending):
            out.append(f"{key}={_quote_env_value(pending[key])}")

    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return path


def _load_options(env: dict[str, str] | None = None) -> dict[str, str]:
    env = env or _parse_env_file()
    options = dict(OPTION_DEFAULTS)
    for key in OPTION_DEFAULTS:
        options[key] = env.get(OPTION_ENV_PREFIX + key.upper(), options[key])

    if env.get("MILLET_LANGUAGE"):
        options["language"] = env["MILLET_LANGUAGE"]
    if env.get("MILLET_SUMMARY_PRESET"):
        options["summary_preset"] = env["MILLET_SUMMARY_PRESET"]
    if env.get("MILLET_SUMMARY_BACKEND"):
        options["summary_backend"] = env["MILLET_SUMMARY_BACKEND"]
    if env.get("MILLET_SUMMARY_MODEL"):
        options["summary_model"] = env["MILLET_SUMMARY_MODEL"]
    if env.get("MILLET_OLLAMA_SINGLEPASS"):
        options["ollama_singlepass"] = "1" if _parse_bool(env["MILLET_OLLAMA_SINGLEPASS"]) else "0"
    return options


def _public_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root().resolve()))
    except ValueError:
        return str(path)


class WebUIState:
    def __init__(self) -> None:
        load_project_env()
        apply_model_cache_environment()
        self.lock = threading.RLock()
        self.session = None
        self.recording_state = "idle"
        self.error: str | None = None
        self.last_output: Path | None = None
        self.last_pdf: Path | None = None
        self.jobs: queue.Queue[Path] = queue.Queue()
        self.job_thread: threading.Thread | None = None
        self.current_job: dict[str, object] | None = None
        self.job_history: list[dict[str, object]] = []

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            status = None
            if self.session is not None:
                try:
                    s = self.session.status()
                    status = {
                        "elapsed": fmt_elapsed(s.elapsed_seconds),
                        "elapsed_seconds": s.elapsed_seconds,
                        "size": fmt_size(s.file_size_bytes),
                        "size_bytes": s.file_size_bytes,
                        "is_alive": s.is_alive,
                        "failed": s.failed,
                        "fail_reason": s.fail_reason,
                        "restart_count": s.restart_count,
                    }
                except Exception as exc:
                    status = {"error": str(exc)}

            return {
                "recording_state": self.recording_state,
                "status": status,
                "error": self.error,
                "last_output": _public_path(self.last_output) if self.last_output else None,
                "last_audio_url": "/file/" + _public_path(self.last_output) if self.last_output else None,
                "last_pdf": _public_path(self.last_pdf) if self.last_pdf else None,
                "current_job": self.current_job,
                "job_history": self.job_history[-8:],
                "sessions": self.list_sessions(limit=12),
            }

    def list_sessions(self, limit: int = 20) -> list[dict[str, object]]:
        root = recordings_dir()
        if not root.exists():
            return []
        sessions: list[dict[str, object]] = []
        for child in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not child.is_dir():
                continue
            files = sorted([p for p in child.iterdir() if p.is_file()])
            audio_file = next(
                (p for p in files if p.suffix.lower() in {".wav", ".ogg", ".mp3", ".m4a"}),
                None,
            )
            sessions.append(
                {
                    "name": child.name,
                    "path": _public_path(child),
                    "mtime": child.stat().st_mtime,
                    "audio_url": "/file/" + _public_path(audio_file) if audio_file else None,
                    "files": [
                        {
                            "name": f.name,
                            "path": _public_path(f),
                            "size": fmt_size(f.stat().st_size),
                            "url": "/file/" + _public_path(f),
                        }
                        for f in files
                    ],
                }
            )
            if len(sessions) >= limit:
                break
        return sessions

    def start_recording(self, options: dict[str, str] | None = None) -> None:
        from millet.capture import check_prerequisites, create_session

        with self.lock:
            if self.recording_state in {"recording", "paused", "draining"}:
                raise RuntimeError("recording is already active")
            self.error = None
            options = options or _load_options()

        issues = check_prerequisites()
        if issues:
            raise RuntimeError("Prerequisites failed: " + "; ".join(issues))

        session = create_session(
            output_dir=_none_if_empty(options.get("output_dir")),
            mic=_none_if_empty(options.get("mic")),
            monitor=_none_if_empty(options.get("monitor")),
            virtual_sink=_parse_bool(options.get("virtual_sink")),
        )
        session.start()
        with self.lock:
            self.session = session
            self.recording_state = "recording"

    def pause_recording(self) -> None:
        with self.lock:
            session = self.session
            if session is None or self.recording_state != "recording":
                raise RuntimeError("not recording")
            session.pause()
            self.recording_state = "paused"

    def resume_recording(self) -> None:
        with self.lock:
            session = self.session
            if session is None or self.recording_state != "paused":
                raise RuntimeError("not paused")
            session.resume()
            self.recording_state = "recording"

    def stop_recording(self, options: dict[str, str] | None = None) -> None:
        with self.lock:
            session = self.session
            if session is None or self.recording_state not in {"recording", "paused"}:
                raise RuntimeError("not recording")
            was_paused = self.recording_state == "paused"
            self.recording_state = "draining"

        thread = threading.Thread(
            target=self._stop_worker,
            args=(session, was_paused, options or _load_options()),
            daemon=True,
        )
        thread.start()

    def _stop_worker(self, session, was_paused: bool, options: dict[str, str]) -> None:
        try:
            if not was_paused:
                time.sleep(DRAIN_SECONDS)
            output = session.stop()
            if not output.exists() or output.stat().st_size == 0:
                raise RuntimeError("No audio was recorded")
            with self.lock:
                self.last_output = output
                self.recording_state = "idle"
                self.session = None
            self.jobs.put(output)
            self._ensure_job_thread(options)
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
                self.recording_state = "error"
                self.session = None

    def _ensure_job_thread(self, options: dict[str, str]) -> None:
        with self.lock:
            if self.job_thread and self.job_thread.is_alive():
                return
            self.job_thread = threading.Thread(target=self._job_consumer, args=(options,), daemon=True)
            self.job_thread.start()

    def _set_job(self, name: str, stage: str, message: str) -> None:
        with self.lock:
            self.current_job = {"name": name, "stage": stage, "message": message, "updated_at": time.time()}

    def _finish_job(self, item: dict[str, object]) -> None:
        with self.lock:
            self.job_history.append(item)
            self.current_job = None
            self.last_pdf = Path(item["pdf"]) if item.get("pdf") else self.last_pdf

    def _job_consumer(self, options: dict[str, str]) -> None:
        while True:
            try:
                output = self.jobs.get(timeout=1.0)
            except queue.Empty:
                return
            try:
                item = self._process_recording(output, options)
                self._finish_job(item)
            except Exception as exc:
                self._finish_job({"name": output.parent.name, "ok": False, "error": str(exc), "finished_at": time.time()})
            finally:
                self.jobs.task_done()

    def _process_recording(self, output: Path, options: dict[str, str]) -> dict[str, object]:
        from millet.transcribe import TranscriptionConfig, ensure_gpu_available
        from millet.transcribe import transcribe as do_transcribe

        name = output.parent.name
        self._set_job(name, "gpu", "Preparing GPU")
        ensure_gpu_available(progress_callback=lambda msg: self._set_job(name, "gpu", msg))

        self._set_job(name, "transcribe", "Transcribing audio")
        config = TranscriptionConfig(
            model=options.get("model") or "large-v3-turbo",
            device=_none_if_auto(options.get("device")),
            torch_device=_none_if_auto(options.get("torch_device")),
            asr_backend=options.get("asr_backend") or "auto",
            mlx_model=_none_if_empty(options.get("mlx_model")),
            compute_type=options.get("compute_type") or "float16",
            batch_size=int(options.get("batch_size") or 16),
            language=options.get("language") or "auto",
            hf_token=os.environ.get("HF_TOKEN"),
            min_speakers=int(options["min_speakers"]) if options.get("min_speakers") else None,
            max_speakers=int(options["max_speakers"]) if options.get("max_speakers") else None,
            skip_alignment=_parse_bool(options.get("skip_alignment")),
            mixdown=options.get("mixdown") or "dual-diarize",
        )
        transcript = do_transcribe(output, config)
        files = transcript.save(output.parent, basename=output.stem)

        summary_result = None
        if _parse_bool(options.get("summarize")):
            self._set_job(name, "summary", "Generating summary")
            summary_result = _generate_summary(
                transcript,
                output.parent,
                output.stem,
                options.get("summary_model") or None,
                files,
                summary_backend=options.get("summary_backend") or None,
                summary_preset=options.get("summary_preset") or None,
                ollama_singlepass=_parse_bool(options.get("ollama_singlepass")),
            )

        self._set_job(name, "pdf", "Generating PDF")
        _generate_pdf(transcript, output.parent, output.stem, summary_result, files)
        return {
            "name": name,
            "ok": True,
            "finished_at": time.time(),
            "audio": str(output),
            "pdf": str(files.get("pdf", "")),
            "files": {k: str(v) for k, v in files.items()},
        }


class WebUIHandler(BaseHTTPRequestHandler):
    server: "MilletHTTPServer"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_text(INDEX_HTML, "text/html; charset=utf-8")
        elif parsed.path == "/app.css":
            self._send_text(APP_CSS, "text/css; charset=utf-8")
        elif parsed.path == "/app.js":
            self._send_text(APP_JS, "application/javascript; charset=utf-8")
        elif parsed.path == "/api/state":
            self._send_json(self.server.state.snapshot())
        elif parsed.path == "/api/settings":
            env = _parse_env_file()
            self._send_json(
                {
                    "env_path": str(_env_path()),
                    "env": {key: env.get(key, os.environ.get(key, "")) for key in ENV_FIELDS},
                    "options": _load_options(env),
                }
            )
        elif parsed.path.startswith("/file/"):
            self._send_file(unquote(parsed.path[len("/file/") :]))
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/settings":
                self._save_settings(payload)
            elif parsed.path == "/api/record/start":
                self.server.state.start_recording(_load_options())
                self._send_json({"ok": True})
            elif parsed.path == "/api/record/pause":
                self.server.state.pause_recording()
                self._send_json({"ok": True})
            elif parsed.path == "/api/record/resume":
                self.server.state.resume_recording()
                self._send_json({"ok": True})
            elif parsed.path == "/api/record/stop":
                self.server.state.stop_recording(_load_options())
                self._send_json({"ok": True})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("content-length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _save_settings(self, payload: dict[str, object]) -> None:
        env_values = {key: str(value) for key, value in dict(payload.get("env") or {}).items() if key in ENV_FIELDS}
        options = {key: str(value) for key, value in dict(payload.get("options") or {}).items() if key in OPTION_DEFAULTS}
        for key, value in options.items():
            env_values[OPTION_ENV_PREFIX + key.upper()] = value
        _write_env_values(env_values)
        for key, value in env_values.items():
            os.environ[key] = value
        self._send_json({"ok": True, "env_path": str(_env_path())})

    def _send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, rel_path: str) -> None:
        root = project_root().resolve()
        path = (root / rel_path).resolve()
        if root not in path.parents and path != root:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("content-length", str(len(body)))
        self.send_header("content-disposition", f'inline; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(body)


class MilletHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], state: WebUIState) -> None:
        super().__init__(server_address, WebUIHandler)
        self.state = state


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    state = WebUIState()
    server = MilletHTTPServer((host, port), state)
    url = f"http://{host}:{server.server_port}/"
    print(f"Millet WebUI running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Millet WebUI")
    finally:
        server.server_close()


INDEX_HTML = """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Millet 控制台</title>
  <link rel="stylesheet" href="/app.css">
</head>
<body>
  <main class="app-shell">
    <aside class="sidebar" aria-label="主要導覽">
      <div class="brand">
        <div class="brand-mark">M</div>
        <div>
          <h1>Millet</h1>
          <p>會議轉錄控制台</p>
        </div>
      </div>
      <nav class="nav">
        <button class="nav-btn active" data-page="record">錄音控制</button>
        <button class="nav-btn" data-page="sessions">會議紀錄</button>
        <button class="nav-btn" data-page="settings">一般設定</button>
        <button class="nav-btn" data-page="advanced">進階設定</button>
      </nav>
      <div class="side-status">
        <span>狀態</span>
        <strong id="pill">待命</strong>
      </div>
    </aside>

    <section class="content">
      <div id="notice" class="notice" role="status"></div>
      <section class="page active" id="page-record">
        <div class="page-head">
          <div>
            <h2>錄音控制</h2>
            <p>開始、暫停、停止錄音；停止後會自動排程轉錄、摘要與 PDF。</p>
          </div>
        </div>

        <div class="record-layout">
          <section class="panel recorder-panel">
            <div class="timer" id="timer">00:00:00</div>
            <div class="meter-row">
              <span id="size">0 KB</span>
              <span id="job">準備就緒</span>
            </div>
            <div class="controls">
              <button id="recordBtn" class="primary">開始錄音</button>
              <button id="pauseBtn">暫停</button>
              <button id="resumeBtn">繼續</button>
              <button id="stopBtn" class="danger">停止</button>
            </div>
            <p id="error" class="error" role="status"></p>
          </section>

          <section class="panel playback-panel">
            <div class="panel-head compact">
              <h3>剛剛錄到的音檔</h3>
              <a id="lastAudioLink" href="#" target="_blank">開啟音檔</a>
            </div>
            <audio id="lastAudio" controls preload="metadata"></audio>
            <p class="hint">停止錄音後，音檔會出現在這裡。你可以先回放確認內容，再到會議紀錄查看輸出檔。</p>
          </section>
        </div>
      </section>

      <section class="page" id="page-sessions">
        <div class="page-head">
          <div>
            <h2>會議紀錄</h2>
            <p>瀏覽最近的錄音、文字稿、摘要與 PDF。每筆會議都可以直接回放音檔。</p>
          </div>
        </div>
        <div id="sessions" class="session-list"></div>
      </section>

      <section class="page" id="page-settings">
        <div class="page-head">
          <div>
            <h2>一般設定</h2>
            <p>常用錄音、轉錄與摘要選項。儲存後會寫入專案的 .env。</p>
          </div>
          <button class="saveBtn">儲存設定</button>
        </div>
        <form id="generalForm" class="settings-grid"></form>
      </section>

      <section class="page" id="page-advanced">
        <div class="page-head">
          <div>
            <h2>進階設定</h2>
            <p>Token、API endpoint、模型快取與較敏感的後端設定集中放在這裡。</p>
          </div>
          <button class="saveBtn">儲存設定</button>
        </div>
        <form id="advancedForm" class="settings-grid"></form>
      </section>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""


APP_CSS = """
:root {
  color-scheme: light;
  --bg: #f4f6f8;
  --panel: #ffffff;
  --ink: #16202a;
  --muted: #637381;
  --line: #d7dee7;
  --blue: #1668b8;
  --blue-soft: #e8f2ff;
  --green: #13795b;
  --red: #b42318;
  --amber: #946200;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  font-family: Inter, "Noto Sans TC", "Microsoft JhengHei", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--ink);
}
button, input, select { font: inherit; }
button {
  min-height: 40px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--ink);
  font-weight: 700;
  cursor: pointer;
}
button:hover { border-color: #9db0bf; }
button:disabled { opacity: .45; cursor: not-allowed; }
a { color: var(--blue); text-decoration: none; }
h1, h2, h3, p { margin: 0; }
.app-shell { display: grid; grid-template-columns: 248px 1fr; min-height: 100vh; }
.sidebar {
  border-right: 1px solid var(--line);
  background: #fff;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.brand { display: flex; gap: 12px; align-items: center; }
.brand-mark {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--blue);
  color: #fff;
  font-weight: 900;
}
.brand h1 { font-size: 24px; line-height: 1; }
.brand p { margin-top: 4px; color: var(--muted); font-size: 13px; }
.nav { display: grid; gap: 8px; }
.nav-btn { text-align: left; padding: 0 12px; background: transparent; }
.nav-btn.active { background: var(--blue-soft); color: #0f4f8c; border-color: #bad7f5; }
.side-status { margin-top: auto; border-top: 1px solid var(--line); padding-top: 14px; display: flex; justify-content: space-between; gap: 10px; color: var(--muted); }
.side-status strong { color: var(--ink); }
.content { padding: 24px; min-width: 0; }
.notice { display: none; margin-bottom: 14px; border: 1px solid #bad7f5; background: var(--blue-soft); color: #0f4f8c; border-radius: 8px; padding: 10px 12px; font-weight: 700; }
.notice.show { display: block; }
.notice.error { border-color: #f0b8b2; background: #fff1ef; color: var(--red); }
.page { display: none; }
.page.active { display: block; }
.page-head { display: flex; align-items: start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.page-head h2 { font-size: 30px; line-height: 1.1; }
.page-head p { margin-top: 8px; color: var(--muted); max-width: 760px; }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  box-shadow: 0 1px 2px rgba(18, 32, 42, .04);
}
.record-layout { display: grid; grid-template-columns: minmax(340px, 460px) 1fr; gap: 16px; align-items: start; }
.timer { font-family: "SFMono-Regular", Consolas, monospace; font-size: 56px; line-height: 1; font-weight: 850; letter-spacing: 0; }
.meter-row { display: flex; justify-content: space-between; gap: 12px; margin: 14px 0 22px; color: var(--muted); }
.controls { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.primary { background: var(--green); border-color: var(--green); color: #fff; }
.danger { background: var(--red); border-color: var(--red); color: #fff; }
.error { margin-top: 12px; color: var(--red); font-weight: 700; min-height: 22px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }
.panel-head.compact h3 { font-size: 18px; }
audio { width: 100%; margin: 8px 0 10px; }
.hint, .muted { color: var(--muted); font-size: 13px; }
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.field.full { grid-column: 1 / -1; }
.checkrow { flex-direction: row; align-items: center; min-height: 40px; }
label { font-size: 13px; font-weight: 800; color: #314457; }
input, select { width: 100%; height: 38px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; background: #fff; color: var(--ink); }
input[type="checkbox"] { width: 18px; height: 18px; }
.session-list { display: grid; gap: 12px; }
.session { background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 16px; display: grid; grid-template-columns: 280px 1fr; gap: 16px; }
.session-title { font-weight: 850; overflow-wrap: anywhere; }
.session audio { margin-top: 12px; }
.files { display: flex; flex-wrap: wrap; gap: 8px; }
.files a { border: 1px solid var(--line); border-radius: 999px; padding: 6px 9px; background: #fff; color: var(--blue); }
@media (max-width: 920px) {
  .app-shell { grid-template-columns: 1fr; }
  .sidebar { position: static; border-right: 0; border-bottom: 1px solid var(--line); }
  .nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .record-layout, .session, .settings-grid { grid-template-columns: 1fr; }
  .controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
"""


APP_JS = """
const $ = (id) => document.getElementById(id);

const generalFields = [
  ["MILLET_RECORDINGS_DIR", "錄音與輸出資料夾", "text", "env"],
  ["MILLET_LANGUAGE", "預設語言", "text", "env"],
  ["model", "Whisper 模型", "text", "options"],
  ["language", "本次轉錄語言", "text", "options"],
  ["asr_backend", "ASR 後端", "select:asr", "options"],
  ["mixdown", "聲道模式", "select:mixdown", "options"],
  ["compute_type", "運算精度", "text", "options"],
  ["batch_size", "批次大小", "number", "options"],
  ["summarize", "產生摘要", "checkbox", "options"],
  ["summary_preset", "摘要預設", "select:preset", "options"],
  ["summary_backend", "摘要後端", "select:backend", "options"],
  ["summary_model", "摘要模型", "text", "options"]
];

const advancedFields = [
  ["HF_TOKEN", "Hugging Face token", "password", "env"],
  ["MILLET_OPENAI_API_KEY", "OpenAI-compatible API key", "password", "env"],
  ["MILLET_OPENAI_BASE_URL", "OpenAI-compatible API URL", "text", "env"],
  ["MILLET_MODEL_CACHE_DIR", "模型快取資料夾", "text", "env"],
  ["MILLET_SUMMARY_PRESET", "全域摘要預設", "select:preset", "env"],
  ["MILLET_SUMMARY_BACKEND", "全域摘要後端", "select:backend", "env"],
  ["MILLET_SUMMARY_MODEL", "全域摘要模型", "text", "env"],
  ["MILLET_OLLAMA_SINGLEPASS", "Ollama 單階段摘要", "checkbox", "env"],
  ["device", "推論裝置", "select:device", "options"],
  ["torch_device", "Torch 裝置", "select:torch", "options"],
  ["mlx_model", "MLX 模型", "text", "options"],
  ["min_speakers", "最少講者數", "number", "options"],
  ["max_speakers", "最多講者數", "number", "options"],
  ["mic", "麥克風來源", "text", "options"],
  ["monitor", "系統音訊來源", "text", "options"],
  ["virtual_sink", "使用虛擬 sink", "checkbox", "options"],
  ["skip_alignment", "略過 word alignment", "checkbox", "options"],
  ["ollama_singlepass", "本次 Ollama 單階段摘要", "checkbox", "options"]
];

const choices = {
  preset: ["", "high-quality", "confidential", "alternative"],
  backend: ["", "ollama", "openrouter", "claudemax", "openai", "tinfoil"],
  device: ["auto", "cuda", "cpu"],
  torch: ["auto", "cuda", "cpu", "mps"],
  asr: ["auto", "whisperx", "mlx", "parakeet"],
  mixdown: ["dual-diarize", "mono", "dual"]
};

let settingsCache = {env: {}, options: {}};

function boolValue(value) {
  return ["1", "true", "yes", "on"].includes(String(value || "").toLowerCase());
}

function setPage(page) {
  document.querySelectorAll(".page").forEach(el => el.classList.toggle("active", el.id === `page-${page}`));
  document.querySelectorAll(".nav-btn").forEach(btn => btn.classList.toggle("active", btn.dataset.page === page));
  location.hash = page;
}

function showNotice(message, isError = false) {
  const notice = $("notice");
  notice.textContent = message || "";
  notice.classList.toggle("show", Boolean(message));
  notice.classList.toggle("error", Boolean(isError));
}

function control(path) {
  return fetch(path, {method: "POST", headers: {"content-type": "application/json"}, body: "{}"})
    .then(r => r.json())
    .then(j => { if (!j.ok) throw new Error(j.error || "操作失敗"); showNotice(""); return refresh(); })
    .catch(e => { $("error").textContent = e.message; showNotice(e.message, true); });
}

function makeField(def) {
  const [key, label, type, group] = def;
  const wrap = document.createElement("div");
  wrap.className = (type === "text" && (key.includes("URL") || key.includes("DIR"))) ? "field full" : "field";
  if (type === "checkbox") wrap.className += " checkrow";
  const id = `${group}_${key}`;
  const lab = document.createElement("label");
  lab.htmlFor = id;
  lab.textContent = label;
  let input;
  if (type.startsWith("select:")) {
    input = document.createElement("select");
    for (const choice of choices[type.split(":")[1]]) {
      const opt = document.createElement("option");
      opt.value = choice;
      opt.textContent = choice || "使用預設";
      input.appendChild(opt);
    }
    input.value = settingsCache[group][key] || "";
  } else {
    input = document.createElement("input");
    input.type = type;
    if (type === "checkbox") input.checked = boolValue(settingsCache[group][key]);
    else input.value = settingsCache[group][key] || "";
  }
  input.id = id;
  input.dataset.group = group;
  input.dataset.key = key;
  if (type === "checkbox") wrap.append(input, lab); else wrap.append(lab, input);
  return wrap;
}

async function loadSettings() {
  settingsCache = await fetch("/api/settings").then(r => r.json());
  $("generalForm").innerHTML = "";
  $("advancedForm").innerHTML = "";
  generalFields.forEach(f => $("generalForm").appendChild(makeField(f)));
  advancedFields.forEach(f => $("advancedForm").appendChild(makeField(f)));
}

function gatherSettings() {
  const payload = {env: {...settingsCache.env}, options: {...settingsCache.options}};
  document.querySelectorAll("[data-group]").forEach(input => {
    payload[input.dataset.group][input.dataset.key] = input.type === "checkbox" ? (input.checked ? "1" : "0") : input.value;
  });
  return payload;
}

async function saveSettings() {
  const result = await fetch("/api/settings", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(gatherSettings())
  }).then(r => r.json());
  showNotice(result.ok ? `已儲存：${result.env_path}` : result.error, !result.ok);
  await loadSettings();
}

function renderSessions(sessions) {
  $("sessions").innerHTML = sessions.map(s => `
    <article class="session">
      <div>
        <div class="session-title">${s.name}</div>
        <div class="muted">${s.path}</div>
        ${s.audio_url ? `<audio controls preload="metadata" src="${s.audio_url}"></audio>` : `<p class="hint">這筆紀錄沒有可回放的音檔。</p>`}
      </div>
      <div class="files">${s.files.map(f => `<a href="${f.url}" target="_blank">${f.name} (${f.size})</a>`).join("")}</div>
    </article>`).join("") || "<p class=\"hint\">還沒有會議紀錄。</p>";
}

function updatePlayback(data) {
  const audio = $("lastAudio");
  const link = $("lastAudioLink");
  if (data.last_audio_url) {
    if (audio.getAttribute("src") !== data.last_audio_url) audio.src = data.last_audio_url;
    link.href = data.last_audio_url;
    link.classList.remove("disabled");
  } else {
    audio.removeAttribute("src");
    link.href = "#";
    link.classList.add("disabled");
  }
}

function zhState(state) {
  return ({idle: "待命", recording: "錄音中", paused: "已暫停", draining: "收尾中", done: "完成", error: "錯誤"})[state] || state;
}

async function refresh() {
  const data = await fetch("/api/state").then(r => r.json());
  $("pill").textContent = zhState(data.recording_state);
  $("timer").textContent = data.status?.elapsed || "00:00:00";
  $("size").textContent = data.status?.size || "0 KB";
  $("job").textContent = data.current_job?.message || (data.job_history?.at(-1)?.ok ? "上一筆處理完成" : "準備就緒");
  $("error").textContent = data.error || "";
  const st = data.recording_state;
  $("recordBtn").disabled = ["recording", "paused", "draining"].includes(st);
  $("pauseBtn").disabled = st !== "recording";
  $("resumeBtn").disabled = st !== "paused";
  $("stopBtn").disabled = !["recording", "paused"].includes(st);
  updatePlayback(data);
  renderSessions(data.sessions || []);
}

document.querySelectorAll(".nav-btn").forEach(btn => btn.onclick = () => setPage(btn.dataset.page));
document.querySelectorAll(".saveBtn").forEach(btn => btn.onclick = (e) => { e.preventDefault(); saveSettings(); });
$("recordBtn").onclick = () => control("/api/record/start");
$("pauseBtn").onclick = () => control("/api/record/pause");
$("resumeBtn").onclick = () => control("/api/record/resume");
$("stopBtn").onclick = () => control("/api/record/stop");

setPage((location.hash || "#record").slice(1));
loadSettings().then(refresh);
setInterval(refresh, 1000);
"""
