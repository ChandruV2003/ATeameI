from __future__ import annotations

import os


_SERVICE = "ATeameI"
_AZDO_USER = "azure_devops_pat"


def get_azdo_pat() -> str | None:
    env = os.environ.get("ATEAMEI_AZDO_PAT", "").strip()
    if env:
        return env
    return get_azdo_pat_from_keychain()


def get_azdo_pat_from_keychain() -> str | None:
    try:
        import keyring  # type: ignore
    except ImportError:
        return None
    try:
        return keyring.get_password(_SERVICE, _AZDO_USER)
    except Exception:
        return None


def set_azdo_pat(token: str) -> None:
    t = (token or "").strip()
    if not t:
        raise ValueError("token is empty")
    try:
        import keyring  # type: ignore
    except ImportError as exc:
        raise RuntimeError("keyring is not installed. Run: pip install -r requirements.txt") from exc
    keyring.set_password(_SERVICE, _AZDO_USER, t)


def delete_azdo_pat() -> None:
    try:
        import keyring  # type: ignore
    except ImportError:
        return
    try:
        keyring.delete_password(_SERVICE, _AZDO_USER)
    except Exception:
        # If it doesn't exist or backend errors, treat as already removed.
        return
