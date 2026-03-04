from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import tempfile
import textwrap
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from faster_whisper import WhisperModel
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from .ollama_client import OllamaClient


console = Console()


def list_devices() -> int:
    # ffmpeg prints device lists to stderr.
    cmd = ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    console.print(Panel.fit(output.strip() or "(no output)", title="ffmpeg device list"))
    return 0


def _project_root() -> Path:
    # Repo-local layout helper (this prototype is intended to run from source).
    return Path(__file__).resolve().parents[1]


def _build_capture_cmd(
    *,
    backend: str,
    device: str,
    sample_rate: int,
    channels: int,
    sck_display_index: int,
    sck_app_bundle_id: str | None,
) -> list[str]:
    if backend == "ffmpeg":
        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "avfoundation",
            "-i",
            device,
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "-",
        ]

    if backend == "sck":
        binary = _project_root() / "bin" / "ateamei-sck-capture"
        if not binary.exists():
            raise FileNotFoundError(
                "ScreenCaptureKit capture binary not found.\n"
                "Build it once with:\n"
                "  bash scripts/build_sck_capture.sh"
            )
        cmd = [
            str(binary),
            "--sample-rate",
            str(sample_rate),
            "--channels",
            str(channels),
            "--display-index",
            str(sck_display_index),
        ]
        if sck_app_bundle_id:
            cmd += ["--app-bundle-id", sck_app_bundle_id]
        return cmd

    raise ValueError(f"Unknown backend: {backend}")


@dataclass
class TranscriptLine:
    t: float
    text: str


def _build_prompt(lines: list[TranscriptLine]) -> str:
    transcript = "\n".join(f"- {l.text}" for l in lines[-40:])
    return textwrap.dedent(
        f"""
        You are a low-latency meeting sidekick.

        Task:
        1) If the most recent speaker utterance contains a question or request, suggest ONE concise reply I can say next (1-3 sentences).
        2) Otherwise, output just "—".
        3) Then list up to 3 clarification questions I should ask (if any).
        4) Then list action items (if any).

        Output format (exact headings):
        Suggested reply:
        Clarifying questions:
        Action items:

        Transcript (most recent last):
        {transcript}
        """
    ).strip()


def _render(transcript: list[TranscriptLine], suggestion: str, status: str) -> Table:
    layout = Table.grid(expand=True)
    layout.add_column(ratio=2)
    layout.add_column(ratio=1)

    transcript_text = "\n".join(l.text for l in transcript[-30:]) or "(listening...)"
    left = Panel(transcript_text, title="Live transcript (tail)", border_style="cyan")

    right = Panel(suggestion or "(assistant idle)", title="Suggested reply", border_style="magenta")
    layout.add_row(left, right)

    footer = Panel(status, title="Status", border_style="green")
    outer = Table.grid(expand=True)
    outer.add_row(layout)
    outer.add_row(footer)
    return outer


async def run(
    *,
    backend: str,
    device: str,
    sample_rate: int,
    channels: int,
    sck_display_index: int,
    sck_app_bundle_id: str | None,
    chunk_seconds: float,
    whisper_model: str,
    ollama_model: str,
    assistant_enabled: bool,
    assistant_interval_seconds: float,
    max_context_lines: int,
    skip_consent_prompt: bool,
) -> int:
    if not skip_consent_prompt:
        console.print(
            Panel.fit(
                "This tool captures audio and performs transcription.\n"
                "Only use it with explicit consent and in compliance with company policy.\n\n"
                'Type "YES" to continue:',
                title="Consent required",
                border_style="red",
            )
        )
        if input().strip() != "YES":
            console.print("Aborted.")
            return 2

    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    model = WhisperModel(whisper_model, device="cpu", compute_type="int8")
    ollama = OllamaClient()

    bytes_per_sample = 2  # s16le
    chunk_bytes = int(sample_rate * channels * bytes_per_sample * chunk_seconds)

    capture_cmd = _build_capture_cmd(
        backend=backend,
        device=device,
        sample_rate=sample_rate,
        channels=channels,
        sck_display_index=sck_display_index,
        sck_app_bundle_id=sck_app_bundle_id,
    )

    proc = await asyncio.create_subprocess_exec(
        *capture_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    transcript: list[TranscriptLine] = []
    suggestion: str = ""
    last_assistant_call = 0.0

    status = f"backend={backend} device={device} sr={sample_rate} ch={channels} chunk={chunk_seconds:.1f}s whisper={whisper_model} assistant={'on' if assistant_enabled else 'off'}"
    stderr_tail: bytearray = bytearray()

    async def _drain_stderr() -> None:
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            stderr_tail.extend(chunk)
            if len(stderr_tail) > 12_000:
                del stderr_tail[:-12_000]

    stderr_task = asyncio.create_task(_drain_stderr())

    async def _read_chunk() -> bytes:
        data = await proc.stdout.readexactly(chunk_bytes)
        return data

    with Live(_render(transcript, suggestion, status), refresh_per_second=6, console=console) as live:
        try:
            while True:
                try:
                    raw = await _read_chunk()
                except asyncio.IncompleteReadError:
                    break

                # Write WAV to temp file for transcription.
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                    with wave.open(tmp.name, "wb") as wf:
                        wf.setnchannels(channels)
                        wf.setsampwidth(bytes_per_sample)
                        wf.setframerate(sample_rate)
                        wf.writeframes(raw)

                    segments, _info = model.transcribe(
                        tmp.name,
                        vad_filter=True,
                        vad_parameters={"min_silence_duration_ms": 500},
                    )

                    text = " ".join(seg.text.strip() for seg in segments).strip()
                    if text:
                        transcript.append(TranscriptLine(t=time.time(), text=text))
                        transcript = transcript[-200:]

                if assistant_enabled and transcript:
                    now = time.time()
                    if now - last_assistant_call >= assistant_interval_seconds:
                        ctx = transcript[-max_context_lines:]
                        prompt = _build_prompt(ctx)
                        try:
                            suggestion = await ollama.chat(ollama_model, prompt)
                        except Exception as exc:
                            suggestion = f"(assistant error: {exc})"
                        last_assistant_call = now

                live.update(_render(transcript, suggestion, status))

        finally:
            proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            stderr_task.cancel()
            with contextlib.suppress(Exception):
                await stderr_task

    if proc.returncode and proc.returncode != 0 and stderr_tail:
        console.print(Panel.fit(stderr_tail.decode(errors="replace"), title="Capture stderr", border_style="red"))

    return 0
