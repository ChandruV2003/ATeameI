# ATeamei (local meeting sidecar prototype)

Local, on-device meeting helper for macOS:
- Captures audio (defaults to mic; can be pointed at a virtual device later for system audio)
- Live transcription (Whisper via `faster-whisper`)
- Suggested replies + action items (local LLM via `ollama`)

## Important (privacy / policy)
Only use this with **explicit consent** from meeting participants and in compliance with your company policies (and any recording/transcription notices required by Teams).

## Requirements
- macOS
- `ffmpeg` installed (`brew install ffmpeg`)
- Python 3.11 (`python3.11`)
- `ollama` installed + a chat model pulled (default: `mistral:7b-instruct`)
- For system audio capture without a virtual device: Swift toolchain (Xcode Command Line Tools) + Screen Recording permission

## Setup
```bash
cd ATeamei
# If you previously had this under a different folder name, recreate the venv:
# rm -rf .venv
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Ensure `ollama` is running and the model exists:
```bash
ollama list
ollama pull mistral:7b-instruct
```

## List audio devices (ffmpeg / avfoundation)
```bash
python -m ateamei list-devices
```

## Run (mic capture by default)
```bash
python -m ateamei run --i-have-consent
```

Common options:
```bash
python -m ateamei run --i-have-consent --chunk-seconds 4 --model small --ollama-model mistral:7b-instruct
```

## (Optional) System audio capture (higher fidelity)
This prototype supports two approaches:

## Web UI (recommended during calls)
Runs a local web UI with the transcript + suggested reply:
```bash
python -m ateamei ui --i-have-consent
```

Defaults:
- `--backend sck`
- `--sck-app-bundle-id com.microsoft.teams`
- `--chunk-seconds 1`
- `--model tiny`

If you want to use mic/avfoundation instead:
```bash
python -m ateamei ui --backend ffmpeg --device ":0" --i-have-consent
```

### Option A: Native system/app audio via ScreenCaptureKit (no virtual driver)
Requires macOS 13+ (build script targets 13.0).

Build the local capture helper (writes to `bin/ateamei-sck-capture`):
```bash
bash scripts/build_sck_capture.sh
```

The first time you run it, macOS will require **Screen Recording** permission for the compiled binary. If capture fails, enable it in:
System Settings → Privacy & Security → Screen Recording.

Run with the ScreenCaptureKit backend:
```bash
python -m ateamei run --backend sck --i-have-consent --chunk-seconds 1 --model tiny
```

If you want to capture only Teams (recommended), pass the bundle id:
```bash
python -m ateamei run --backend sck --sck-app-bundle-id com.microsoft.teams --i-have-consent --chunk-seconds 1 --model tiny
```

### Option B: Virtual audio device + ffmpeg (avfoundation)
macOS doesn’t provide a built-in “loopback” input, so some setups use a virtual device (e.g., BlackHole) and route Teams output into it.

Once configured, select that device index using `list-devices` and then pass `--device`:
```bash
python -m ateamei list-devices
python -m ateamei run --backend ffmpeg --device ":<INDEX>" --i-have-consent
```

## Auth (Azure DevOps PAT)
Never commit or paste PATs into git.

Store your Azure DevOps PAT in macOS Keychain:
```bash
python -m ateamei auth set-azdo
```

Check whether it’s configured (does not print the PAT):
```bash
python -m ateamei auth status
```

Remove it:
```bash
python -m ateamei auth unset-azdo
```

## Standup (8:30am) helper
Store the standup meeting URL locally (not committed):
```bash
python -m ateamei standup set-url "<TEAMS_JOIN_URL>"
```

Install a LaunchAgent that opens the link at **8:30am Mon–Fri**:
```bash
python -m ateamei standup install
```

You can also open it on-demand:
```bash
python -m ateamei standup join
```

## Memory vault (lightweight “long-term memory”)
This is a local SQLite + FTS store you can use to save **decisions, requirements, PR comments, links, and outcomes** (recommended) or paste larger chat snippets.

Add an entry (reads stdin):
```bash
pbpaste | python -m ateamei mem add --source codex --tags "pinnacleapi,16880"
```

Search:
```bash
python -m ateamei mem search "fn_GetPartitionHierarchyByPartition"
```

Ask (uses Ollama to synthesize an answer from top hits):
```bash
python -m ateamei mem ask "What was the final decision on ALOC partition visibility?"
```

Storage location defaults to `~/.codex/ateamei/memory.sqlite` (override with `ATEAMEI_MEMORY_PATH`).

Optional semantic retrieval:
- Set `ATEAMEI_EMBED_MODEL` (example: `mistral:7b-instruct`) to store embeddings for new entries.
- `mem ask` will fall back to semantic matches when FTS returns no results.

## Notes / limitations
- Whisper is run on short chunks, so transcript latency is typically a few seconds.
- Suggested replies are best-effort; always verify before sending.
