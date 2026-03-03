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
macOS doesn't provide a built-in “loopback” input. The usual approach is to install a virtual device (e.g., BlackHole) and route Teams output into it.

This prototype already supports capturing from **any** avfoundation input device—once you have a loopback device configured, pass `--device` to select it.

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
