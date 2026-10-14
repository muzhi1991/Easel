"""Recover explicit media directives omitted by OpenClaw's text-only HTTP stream.

Only assistant text from the exact gateway run is considered. No filesystem scan,
reasoning extraction, or inference from prose is used to discover deliverables.
"""
from pathlib import Path
import re
from urllib.parse import quote


class MediaHistoryUnavailable(Exception):
    pass


def media_suffix(history: dict, session_key: str, run_id: str, outputs: Path, delivered: str) -> str:
    if not run_id or history.get('sessionKey') != session_key:
        raise MediaHistoryUnavailable('会话或轮次标识不匹配')
    matched = [m for m in history.get('messages', []) if isinstance(m, dict)
               and m.get('role') == 'assistant' and m.get('__openclaw', {}).get('runId') == run_id]
    if not matched:
        raise MediaHistoryUnavailable('未找到本轮完整回复')
    refs = []
    for message in matched:
        blocks = message.get('content', [])
        if isinstance(blocks, str):
            blocks = [{'type': 'text', 'text': blocks}]
        for block in blocks:
            if not isinstance(block, dict) or block.get('type') != 'text':
                continue
            text = block.get('text', '')
            if '...(truncated)...' in text:
                raise MediaHistoryUnavailable('本轮历史被截断')
            fence = None
            for line in text.splitlines():
                stripped = line.strip()
                marker = re.match(r'^(`{3,}|~{3,})', stripped)
                if marker:
                    char = marker[1][0]
                    if fence is None:
                        fence = char
                    elif fence == char:
                        fence = None
                    continue
                if fence:
                    continue
                directive = re.fullmatch(r'MEDIA:\s*(.+)', stripped)
                if directive:
                    value = directive[1].strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'", '`'):
                        value = value[1:-1]
                    refs.append(value)
    rendered, seen = [], set()
    root = outputs.resolve()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        try:
            path = Path(ref)
            if not path.is_absolute():
                # Only the documented project outputs namespace is supported.
                if not ref.startswith('outputs/'):
                    raise ValueError('unsupported media reference')
                path = root.parent / path
            path = path.resolve()
            rel = path.relative_to(root)
            if not rel.parts or any(part.startswith('.') or part.startswith('_') for part in rel.parts):
                raise ValueError('not a public output')
            if not path.is_file():
                raise ValueError('missing output')
        except (ValueError, OSError, RuntimeError):
            note = '（本轮有媒体文件无法展示，请在内容库检查产物是否存在。）'
            if note not in rendered and note not in delivered:
                rendered.append(note)
            continue
        url = '/api/media/' + quote(rel.as_posix(), safe='/')
        if url in delivered or ref in delivered or url in seen:
            continue
        seen.add(url)
        label = re.sub(r'([\\\[\]])', r'\\\1', path.name)
        image = path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.avif', '.bmp', '.ico'}
        rendered.append(f'{"!" if image else ""}[{label}]({url})')
    return '\n\n' + '\n\n'.join(rendered) if rendered else ''
