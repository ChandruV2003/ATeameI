from __future__ import annotations

import argparse
import asyncio
import sys

from .standup import get_standup_url, join_standup, set_standup_url, write_launchagent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ateamei",
        description="ATeamei: local meeting sidecar prototype (transcribe + suggested replies).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list-devices", help="List avfoundation audio devices via ffmpeg.")
    p_list.set_defaults(func=_cmd_list_devices)

    p_mem = sub.add_parser("mem", help="Local memory vault (notes / chat snippets).")
    mem_sub = p_mem.add_subparsers(dest="mem_cmd", required=True)

    p_mem_add = mem_sub.add_parser("add", help="Add a memory entry (reads stdin by default).")
    p_mem_add.add_argument("--source", default="manual", help="Source label (manual, codex, meeting, etc).")
    p_mem_add.add_argument("--tags", default="", help="Comma-separated tags.")
    p_mem_add.add_argument("--file", default="", help="Read entry text from a file instead of stdin.")
    p_mem_add.add_argument(
        "--allow-secrets",
        action="store_true",
        help="Disable basic redaction (not recommended).",
    )
    p_mem_add.set_defaults(func=_cmd_mem_add)

    p_mem_search = mem_sub.add_parser("search", help="Full-text search memory entries.")
    p_mem_search.add_argument("query", help="FTS query string.")
    p_mem_search.add_argument("--limit", type=int, default=10)
    p_mem_search.set_defaults(func=_cmd_mem_search)

    p_mem_ask = mem_sub.add_parser("ask", help="Ask a question using retrieved memory context (Ollama).")
    p_mem_ask.add_argument("question", help="Question to answer.")
    p_mem_ask.add_argument("--ollama-model", default="mistral:7b-instruct")
    p_mem_ask.add_argument("--limit", type=int, default=12, help="How many memory hits to include.")
    p_mem_ask.set_defaults(func=_cmd_mem_ask)

    p_mem_export = mem_sub.add_parser("export", help="Export latest entries.")
    p_mem_export.add_argument("--limit", type=int, default=50)
    p_mem_export.set_defaults(func=_cmd_mem_export)

    p_run = sub.add_parser("run", help="Run transcription + assistant loop.")
    p_run.add_argument(
        "--backend",
        choices=["ffmpeg", "sck"],
        default="ffmpeg",
        help="Audio capture backend. ffmpeg=avfoundation input device, sck=ScreenCaptureKit system/app audio (macOS).",
    )
    p_run.add_argument(
        "--device",
        default=":0",
        help='ffmpeg avfoundation input spec (audio-only is typically ":<index>"). Default ":0".',
    )
    p_run.add_argument(
        "--sck-display-index",
        type=int,
        default=0,
        help="(backend=sck) Display index to capture (usually 0 for main display).",
    )
    p_run.add_argument(
        "--sck-app-bundle-id",
        default="",
        help="(backend=sck) Optional bundle id to filter capture to a single app (e.g. com.microsoft.teams).",
    )
    p_run.add_argument("--sample-rate", type=int, default=16_000, help="PCM sample rate.")
    p_run.add_argument("--channels", type=int, default=1, help="PCM channels.")
    p_run.add_argument("--chunk-seconds", type=float, default=4.0, help="Chunk duration for transcription.")
    p_run.add_argument(
        "--model",
        default="small",
        help="faster-whisper model size/name (e.g. tiny, base, small, medium).",
    )
    p_run.add_argument(
        "--ollama-model",
        default="mistral:7b-instruct",
        help="Ollama model to use for suggestions.",
    )
    p_run.add_argument(
        "--no-assistant",
        action="store_true",
        help="Disable suggested replies (transcription only).",
    )
    p_run.add_argument(
        "--assistant-interval-seconds",
        type=float,
        default=10.0,
        help="Minimum seconds between assistant calls.",
    )
    p_run.add_argument(
        "--max-context-lines",
        type=int,
        default=40,
        help="How many transcript lines to include in the assistant context.",
    )
    p_run.add_argument(
        "--i-have-consent",
        action="store_true",
        help="Skip the interactive consent prompt.",
    )
    p_run.set_defaults(func=_cmd_run)

    p_ui = sub.add_parser("ui", help="Run local web UI (live transcript + suggested replies).")
    p_ui.add_argument("--port", type=int, default=5080, help="Local port to bind (default 5080).")
    p_ui.add_argument(
        "--no-open",
        action="store_true",
        help="Don't auto-open a browser tab.",
    )
    p_ui.add_argument(
        "--backend",
        choices=["ffmpeg", "sck"],
        default="sck",
        help="Audio capture backend (default: sck).",
    )
    p_ui.add_argument("--device", default=":0", help='(backend=ffmpeg) avfoundation input spec, e.g. ":0".')
    p_ui.add_argument("--sck-display-index", type=int, default=0, help="(backend=sck) Display index (default 0).")
    p_ui.add_argument(
        "--sck-app-bundle-id",
        default="com.microsoft.teams",
        help='(backend=sck) App bundle id to capture (default "com.microsoft.teams").',
    )
    p_ui.add_argument("--sample-rate", type=int, default=16_000, help="PCM sample rate.")
    p_ui.add_argument("--channels", type=int, default=1, help="PCM channels.")
    p_ui.add_argument("--chunk-seconds", type=float, default=1.0, help="Chunk duration for transcription.")
    p_ui.add_argument("--model", default="tiny", help="faster-whisper model (default tiny for latency).")
    p_ui.add_argument("--ollama-model", default="mistral:7b-instruct", help="Ollama chat model.")
    p_ui.add_argument(
        "--no-assistant",
        action="store_true",
        help="Disable suggested replies (transcript only).",
    )
    p_ui.add_argument(
        "--assistant-interval-seconds",
        type=float,
        default=6.0,
        help="Minimum seconds between assistant calls.",
    )
    p_ui.add_argument(
        "--max-context-lines",
        type=int,
        default=40,
        help="How many transcript lines to include in the assistant context.",
    )
    p_ui.add_argument(
        "--i-have-consent",
        action="store_true",
        help="Skip the interactive consent prompt.",
    )
    p_ui.set_defaults(func=_cmd_ui)

    p_standup = sub.add_parser("standup", help="Standup helper (store URL, join, install schedule).")
    standup_sub = p_standup.add_subparsers(dest="standup_cmd", required=True)

    p_standup_set = standup_sub.add_parser("set-url", help="Save the standup Teams join URL locally.")
    p_standup_set.add_argument("url", help="Teams meeting join URL.")
    p_standup_set.set_defaults(func=_cmd_standup_set_url)

    p_standup_join = standup_sub.add_parser("join", help="Open the standup Teams join URL (macOS open).")
    p_standup_join.set_defaults(func=_cmd_standup_join)

    p_standup_install = standup_sub.add_parser(
        "install",
        help="Create a LaunchAgent that opens the standup link at 8:30am Mon-Fri (local machine).",
    )
    p_standup_install.add_argument(
        "--url",
        default="",
        help="Optionally set the URL before installing.",
    )
    p_standup_install.set_defaults(func=_cmd_standup_install)

    p_standup_status = standup_sub.add_parser("status", help="Show whether the URL and LaunchAgent exist.")
    p_standup_status.set_defaults(func=_cmd_standup_status)

    p_auth = sub.add_parser("auth", help="Auth helpers (store secrets in Keychain; never commit).")
    auth_sub = p_auth.add_subparsers(dest="auth_cmd", required=True)

    p_auth_set = auth_sub.add_parser("set-azdo", help="Store Azure DevOps PAT in macOS Keychain.")
    p_auth_set.add_argument("--token", default="", help="PAT value (discouraged; prefer prompt).")
    p_auth_set.add_argument(
        "--stdin",
        action="store_true",
        help="Read PAT from stdin (e.g. pbpaste | ...).",
    )
    p_auth_set.set_defaults(func=_cmd_auth_set_azdo)

    p_auth_unset = auth_sub.add_parser("unset-azdo", help="Remove Azure DevOps PAT from Keychain.")
    p_auth_unset.set_defaults(func=_cmd_auth_unset_azdo)

    p_auth_status = auth_sub.add_parser("status", help="Show whether auth is configured (no secrets printed).")
    p_auth_status.set_defaults(func=_cmd_auth_status)

    return parser


def _cmd_list_devices(_: argparse.Namespace) -> int:
    from .runner import list_devices
    return list_devices()

def _cmd_mem_add(args: argparse.Namespace) -> int:
    from .memory import add_entry
    text = ""
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    entry_id = add_entry(
        text=text,
        source=args.source,
        tags=args.tags,
        allow_secrets=args.allow_secrets,
    )
    print(entry_id)
    return 0


def _cmd_mem_search(args: argparse.Namespace) -> int:
    from .memory import search_entries
    rows = search_entries(args.query, limit=args.limit)
    for row in rows:
        print(f"{row['id']}\t{row['created_at']}\t{row['source']}\t{row['tags']}\t{row['snippet']}")
    return 0


def _cmd_mem_export(args: argparse.Namespace) -> int:
    from .memory import export_entries
    rows = export_entries(limit=args.limit)
    for row in rows:
        print(f"## {row['id']}  {row['created_at']}  source={row['source']}  tags={row['tags']}")
        print(row["text"].rstrip())
        print()
    return 0


def _cmd_mem_ask(args: argparse.Namespace) -> int:
    from .memory import ask_memory
    answer = asyncio.run(ask_memory(args.question, ollama_model=args.ollama_model, limit=args.limit))
    print(answer)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from .runner import run
    return asyncio.run(
        run(
            backend=args.backend,
            device=args.device,
            sample_rate=args.sample_rate,
            channels=args.channels,
            sck_display_index=args.sck_display_index,
            sck_app_bundle_id=(args.sck_app_bundle_id or None),
            chunk_seconds=args.chunk_seconds,
            whisper_model=args.model,
            ollama_model=args.ollama_model,
            assistant_enabled=not args.no_assistant,
            assistant_interval_seconds=args.assistant_interval_seconds,
            max_context_lines=args.max_context_lines,
            skip_consent_prompt=args.i_have_consent,
        )
    )


def _cmd_ui(args: argparse.Namespace) -> int:
    from .runner import run
    from .ui_server import UiState, serve

    async def _main() -> int:
        state = UiState()

        async def _runner() -> int:
            return await run(
                backend=args.backend,
                device=args.device,
                sample_rate=args.sample_rate,
                channels=args.channels,
                sck_display_index=args.sck_display_index,
                sck_app_bundle_id=(args.sck_app_bundle_id or None),
                chunk_seconds=args.chunk_seconds,
                whisper_model=args.model,
                ollama_model=args.ollama_model,
                assistant_enabled=not args.no_assistant,
                assistant_interval_seconds=args.assistant_interval_seconds,
                max_context_lines=args.max_context_lines,
                skip_consent_prompt=args.i_have_consent,
                render_tui=False,
                on_update=state.broadcast,
            )

        runner_task = asyncio.create_task(_runner())
        return await serve(
            state=state,
            port=args.port,
            open_browser=not args.no_open,
            run_task=runner_task,
        )

    return asyncio.run(_main())

def _cmd_standup_set_url(args: argparse.Namespace) -> int:
    set_standup_url(args.url)
    print("ok")
    return 0


def _cmd_standup_join(_: argparse.Namespace) -> int:
    join_standup()
    return 0


def _cmd_standup_install(args: argparse.Namespace) -> int:
    if args.url:
        set_standup_url(args.url)

    url = get_standup_url()
    if not url:
        raise ValueError("Standup URL not configured. Run: python -m ateamei standup set-url <url>")

    plist_path = write_launchagent()
    print(f"Wrote LaunchAgent: {plist_path}")
    print("To enable:")
    print(f"  launchctl load -w {plist_path}")
    print("To disable:")
    print(f"  launchctl unload -w {plist_path}")
    return 0


def _cmd_standup_status(_: argparse.Namespace) -> int:
    url = get_standup_url()
    # We do not create files on status; just report expected locations.
    from .standup import launchagent_path  # local import to keep CLI startup light
    from .standup import standup_url_path

    url_path = standup_url_path()
    la_path = launchagent_path()

    print(f"url_file={url_path} exists={url_path.exists()}")
    print(f"launchagent={la_path} exists={la_path.exists()}")
    print(f"url_set={'yes' if url else 'no'}")
    return 0


def _cmd_auth_set_azdo(args: argparse.Namespace) -> int:
    from .secrets import set_azdo_pat

    token = (args.token or "").strip()
    if not token and args.stdin:
        token = sys.stdin.read().strip()
    if not token:
        from getpass import getpass

        token = getpass("Azure DevOps PAT (input hidden): ").strip()

    set_azdo_pat(token)
    print("ok")
    return 0


def _cmd_auth_unset_azdo(_: argparse.Namespace) -> int:
    from .secrets import delete_azdo_pat

    delete_azdo_pat()
    print("ok")
    return 0


def _cmd_auth_status(_: argparse.Namespace) -> int:
    import os

    from .secrets import get_azdo_pat_from_keychain

    env_set = bool(os.environ.get("ATEAMEI_AZDO_PAT", "").strip())
    keychain_set = bool((get_azdo_pat_from_keychain() or "").strip())

    print(f"azdo_env_set={env_set}")
    print(f"azdo_keychain_set={keychain_set}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pragma: no cover - CLI guardrail
        print(f"error: {exc}", file=sys.stderr)
        return 1
