"""One account namespace per persona; general mode retains all legacy paths.

HTTP requests use a ContextVar, child processes use an explicit environment value.
Neither changes the process-wide environment or the selected persona of another tab.
"""
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path

from easel.persona import valid_persona_name

current_persona: ContextVar[str | None] = ContextVar('account_persona', default=None)


def persona() -> str:
    value = current_persona.get()
    value = os.environ.get('EASEL_ACCOUNT_PERSONA', '') if value is None else value
    if value and not valid_persona_name(value):
        raise ValueError('无效的账号画像')
    return value


def key() -> str:
    value = persona()
    return hashlib.sha256(value.encode()).hexdigest()[:20] if value else ''


def directory(legacy: Path) -> Path:
    scope = key()
    return legacy / 'personas' / scope if scope else legacy


def browser_base(explicit=None) -> Path:
    # An active persona always wins over old commands containing --profile-base.
    if persona():
        return directory(Path.home() / '.easel-browser-profiles')
    return Path(explicit).expanduser() if explicit else Path.home() / '.easel-browser-profiles'


def environment(env: dict) -> dict:
    return {**env, 'EASEL_ACCOUNT_PERSONA': persona()}


def cache_key(platform: str) -> str:
    return f'{key()}:{platform}' if key() else platform


def cookie_path(root: Path) -> Path:
    return browser_base() / 'cookies.json' if key() else root / 'cookies.json'


def wechat_config(legacy: Path) -> Path:
    return browser_base() / 'wechat-publisher.yaml' if key() else legacy


def bind_session(sessions: Path, session_id: str, selected_persona: str) -> None:
    """Persist the authoritative namespace for a gateway session (no credentials)."""
    if selected_persona and not valid_persona_name(selected_persona):
        raise ValueError('无效的账号画像')
    directory = sessions / 'account-scopes'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(session_id.encode()).hexdigest() + '.json')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'persona': selected_persona}, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)
