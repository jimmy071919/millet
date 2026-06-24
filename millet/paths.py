"""Central path resolution for millet (a.k.a. meetscribe).

Historically every module hardcoded its own ``~/.config/meet/...`` and
recordings-directory constants.  This module consolidates that logic in
one place and adds an optional ``team`` dimension so a scribe recording
for multiple teams can keep voiceprints, sync config, and recordings
separated locally.

Team-aware layout (when ``team`` is given)::

    ~/.config/meet/<team>/speaker_profiles.json
    ~/.config/meet/<team>/sync_config.json
    <project>/millet-output/<team>/

Global layout (when ``team`` is None — unchanged, back-compatible)::

    ~/.config/meet/speaker_profiles.json
    ~/.config/meet/sync_config.json
    <project>/millet-output/

Resolution is evaluated at call time (not import time) so callers that
override ``$HOME`` or the env vars between import and use get the right
path.

Environment overrides (no-team escape hatches, preserved for
back-compat):

* ``MEET_PROFILES_PATH`` — absolute path to the profiles DB.  When set
  AND no ``team`` is requested, it wins.  When a ``team`` is requested
  the env override is ignored (an explicit team is more specific than a
  process-wide override).
* ``MEET_CONFIG_DIR`` — root of the config tree (default
  ``~/.config/meet``).
* ``MEET_RECORDINGS_DIR`` — root of the recordings tree (default
  ``<project>/millet-output``).
"""

from __future__ import annotations

import os
import re
import warnings
from pathlib import Path

# ── env-var rename (meetscribe/meet → millet), v0.9.1 ────────────────────────
#
# The pipeline is being renamed meetscribe/meet → millet.  Env vars get a
# new ``MILLET_*`` spelling; the legacy ``MEETSCRIBE_*`` / ``MEET_*``
# names still work for one minor release with a one-time
# DeprecationWarning.  ``getenv_renamed`` centralizes that fallback.

_RENAME_WARNED: set[str] = set()


def getenv_renamed(
    new_name: str,
    *legacy_names: str,
    default: str | None = None,
) -> str | None:
    """Read ``new_name`` from the env, falling back to legacy aliases.

    The first set (in order: new, then each legacy) wins.  Reading via a
    legacy alias emits a one-time ``DeprecationWarning`` naming the new
    variable.  Returns ``default`` when nothing is set.
    """
    val = os.environ.get(new_name)
    if val is not None:
        return val
    for legacy in legacy_names:
        val = os.environ.get(legacy)
        if val is not None:
            if legacy not in _RENAME_WARNED:
                _RENAME_WARNED.add(legacy)
                warnings.warn(
                    f"environment variable {legacy} is deprecated; "
                    f"use {new_name} instead (the meetscribe→millet rename; "
                    "the legacy name is honored for one more release).",
                    DeprecationWarning,
                    stacklevel=2,
                )
            return val
    return default

# A team slug mirrors vezir's contract: 3-32 chars, lowercase alnum +
# hyphen, must start with a letter.  We validate defensively so a bad
# value can never escape its directory.
_TEAM_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{2,31}$")

_PROFILES_FILENAME = "speaker_profiles.json"
_SYNC_FILENAME = "sync_config.json"
_MODEL_CACHE_DIRNAME = ".millet-models"
_OUTPUT_DIRNAME = "millet-output"

_DOTENV_LOADED = False


def _parse_dotenv_value(raw: str) -> str:
    """Parse a small, shell-like .env value without expanding variables."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        quote = raw[0]
        raw = raw[1:-1]
        if quote == '"':
            return bytes(raw, "utf-8").decode("unicode_escape")
    return raw


def load_project_env(env_path: str | Path | None = None) -> Path | None:
    """Load KEY=VALUE pairs from the project .env file if present.

    Existing process environment variables win.  This intentionally supports
    only the common .env subset millet needs: blank lines, # comments, optional
    ``export KEY=VALUE``, and quoted or unquoted values.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED and env_path is None:
        return None

    path = Path(env_path).expanduser() if env_path else project_root() / ".env"
    if not path.exists():
        _DOTENV_LOADED = True
        return None

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        os.environ.setdefault(key, _parse_dotenv_value(value))

    _DOTENV_LOADED = True
    return path



def _validate_team(team: str | None) -> str | None:
    """Return the team slug if valid, or None.  Raise on malformed input."""
    if team is None:
        return None
    team = team.strip()
    if not team:
        return None
    if not _TEAM_SLUG_RE.match(team):
        raise ValueError(
            f"invalid team slug {team!r}: must be 3-32 chars, lowercase "
            "letters/digits/hyphens, starting with a letter"
        )
    return team


def config_dir(team: str | None = None) -> Path:
    """Root config directory, optionally scoped to a team.

    ``~/.config/meet`` (or ``$MEET_CONFIG_DIR``), plus ``/<team>`` when a
    team is given.
    """
    team = _validate_team(team)
    root = getenv_renamed("MILLET_CONFIG_DIR", "MEET_CONFIG_DIR", default="")
    base = Path(root).expanduser() if root else Path.home() / ".config" / "meet"
    return base / team if team else base


def profiles_path(team: str | None = None) -> Path:
    """Path to the speaker-profiles DB.

    Precedence:
      1. ``team`` given → ``<config_dir>/<team>/speaker_profiles.json``
         (env override intentionally ignored — explicit team wins).
      2. ``$MEET_PROFILES_PATH`` if set.
      3. ``<config_dir>/speaker_profiles.json``.
    """
    team = _validate_team(team)
    if team:
        return config_dir(team) / _PROFILES_FILENAME
    env = getenv_renamed("MILLET_PROFILES_PATH", "MEET_PROFILES_PATH", default="")
    if env:
        return Path(env).expanduser()
    return config_dir() / _PROFILES_FILENAME


def sync_config_path(team: str | None = None) -> Path:
    """Path to the sync_config.json, optionally scoped to a team."""
    return config_dir(team) / _SYNC_FILENAME


def default_language() -> str:
    """Default transcription/summary language for CLI commands."""
    return getenv_renamed("MILLET_LANGUAGE", "MEETSCRIBE_LANGUAGE", default="zh") or "zh"


def recordings_dir(team: str | None = None) -> Path:
    """Root recordings directory, optionally scoped to a team.

    ``<project>/millet-output`` (or ``$MILLET_RECORDINGS_DIR``), plus
    ``/<team>`` when a team is given.
    """
    team = _validate_team(team)
    root = getenv_renamed("MILLET_RECORDINGS_DIR", "MEET_RECORDINGS_DIR", default="")
    base = _project_relative_path(root) if root else project_root() / _OUTPUT_DIRNAME
    return base / team if team else base


def project_root() -> Path:
    """Return the source/project root that contains the ``millet`` package."""
    return Path(__file__).resolve().parent.parent


def _project_relative_path(value: str | Path) -> Path:
    """Resolve relative config paths against the project root."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root() / path


def model_cache_dir() -> Path:
    """Root directory for persistent local model caches.

    ``MILLET_MODEL_CACHE_DIR`` lets operators place model weights on a
    large/shared disk.  When unset, source installs keep the cache inside the
    project checkout so repeated runs do not redownload Hugging Face /
    transformers / torch assets into ephemeral home directories.
    """
    root = getenv_renamed(
        "MILLET_MODEL_CACHE_DIR",
        "MEETSCRIBE_MODEL_CACHE_DIR",
        default="",
    )
    return _project_relative_path(root) if root else project_root() / _MODEL_CACHE_DIRNAME


def huggingface_home() -> Path:
    """Persistent Hugging Face home used by millet when HF_HOME is unset."""
    return Path(os.environ.get("HF_HOME", model_cache_dir() / "huggingface")).expanduser()


def huggingface_hub_dir() -> Path:
    """Persistent Hugging Face hub cache directory."""
    return Path(
        os.environ.get("HF_HUB_CACHE", huggingface_home() / "hub")
    ).expanduser()


def huggingface_token_path() -> Path:
    """Project-local Hugging Face token file.

    The file is intentionally outside ``~/.cache`` so a source checkout can be
    self-contained for offline-ish repeated use after the first authorized
    download.
    """
    return huggingface_home() / "token"


def save_huggingface_token(token: str) -> Path:
    """Persist a Hugging Face token in millet's local model cache."""
    token_path = huggingface_token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token.strip() + "\n", encoding="utf-8")
    try:
        token_path.chmod(0o600)
    except OSError:
        pass
    return token_path


def torch_home() -> Path:
    """Persistent torch/torchaudio cache root used by alignment downloads."""
    return Path(os.environ.get("TORCH_HOME", model_cache_dir() / "torch")).expanduser()


def apply_model_cache_environment() -> None:
    """Point model-download libraries at millet's persistent cache.

    Called early by importable modules before Hugging Face / transformers /
    torchaudio are imported.  User-provided env vars always win.
    """
    hf_home = huggingface_home()
    os.environ.setdefault("HF_HOME", str(hf_home))
    os.environ.setdefault("HF_HUB_CACHE", str(huggingface_hub_dir()))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.environ["HF_HUB_CACHE"])
    os.environ.setdefault("HF_XET_CACHE", str(hf_home / "xet"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(hf_home / "transformers"))
    os.environ.setdefault("TORCH_HOME", str(torch_home()))
