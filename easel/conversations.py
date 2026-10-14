"""Easel's shared UI history. Agent history remains owned by the selected runtime.

Each transaction changes one conversation; revision checks reject stale browsers.
Deleted IDs remain tombstones so importing an old browser backup cannot revive them.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


class Conversations:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS conversations '
                       '(id TEXT PRIMARY KEY, data TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY, conversation TEXT NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _get(db, identifier):
        row = db.execute('SELECT data FROM conversations WHERE id=? AND deleted=0', (identifier,)).fetchone()
        if row is None:
            raise Missing('会话已删除或不存在')
        return json.loads(row[0])

    @staticmethod
    def _put(db, data):
        data['revision'] += 1
        db.execute('UPDATE conversations SET data=? WHERE id=?',
                   (json.dumps(data, ensure_ascii=False), data['id']))
        return data

    def list(self):
        with self.transaction() as db:
            rows = [json.loads(row[0]) for row in db.execute('SELECT data FROM conversations WHERE deleted=0')]
        return sorted(rows, key=lambda s: s['created'], reverse=True)

    def get(self, identifier):
        with self.transaction() as db:
            return self._get(db, identifier)

    def create(self, data, *, importing=False):
        data = dict(data)
        identifier = data['id']
        with self.transaction() as db:
            row = db.execute('SELECT data, deleted FROM conversations WHERE id=?', (identifier,)).fetchone()
            if row:
                if not importing:
                    raise Conflict('会话标识已存在，请刷新后重试')
                # Retry of the same import is safe, but never overwrites newer data.
                return None if row[1] else json.loads(row[0])
            data.update(source='server', revision=1)
            data.pop('pendingTurnId', None)
            data['agentSessionId'] = identifier.removeprefix('shared_')
            if not importing:
                data['messages'] = []
            elif data['messages'] and data['messages'][-1]['role'] == 'user':
                data['messages'].append({'role': 'assistant', 'content': '（旧会话的上一轮未完成，请重试。）'})
            db.execute('INSERT INTO conversations(id, data) VALUES (?, ?)',
                       (identifier, json.dumps(data, ensure_ascii=False)))
            return data

    def patch(self, identifier, revision, changes):
        with self.transaction() as db:
            data = self._get(db, identifier)
            self._check(data, revision)
            if 'persona' in changes and changes['persona'] != data.get('persona') and data['messages']:
                raise Conflict('已有对话的画像不能修改，请新建对话')
            data.update(changes)
            return self._put(db, data)

    @staticmethod
    def _check(data, revision):
        if data['revision'] != revision:
            raise Conflict('会话已在其他窗口更新，请刷新后重试')

    def delete(self, identifier, revision):
        with self.transaction() as db:
            data = self._get(db, identifier)
            self._check(data, revision)
            if data.get('pendingTurnId'):
                raise Conflict('请先停止正在运行的对话')
            # Keep only the tombstone, not the deleted transcript.
            db.execute('UPDATE conversations SET deleted=1, data=? WHERE id=?', ('{}', identifier))

    def begin(self, identifier, revision, turn_id, message, title, truncate_at=None):
        with self.transaction() as db:
            data = self._get(db, identifier)
            self._check(data, revision)
            if data.get('pendingTurnId'):
                raise Conflict('此会话正在回复中，请等待完成或先停止')
            if db.execute('SELECT 1 FROM turns WHERE id=?', (turn_id,)).fetchone():
                raise Conflict('此轮消息已提交，请刷新接回结果')
            if truncate_at is not None:
                if not 0 <= truncate_at < len(data['messages']) or data['messages'][truncate_at]['role'] != 'user':
                    raise Conflict('重试的消息已变化，请刷新后重试')
                data['messages'] = data['messages'][:truncate_at]
            data['messages'].append(message)
            data['title'] = title or data['title']
            data['pendingTurnId'] = turn_id
            data['turnStarted'] = time.time()
            db.execute('INSERT INTO turns VALUES (?, ?)', (turn_id, identifier))
            return self._put(db, data)

    def finish(self, identifier, turn_id, message, session_key=None):
        with self.transaction() as db:
            data = self._get(db, identifier)
            if data.get('pendingTurnId') != turn_id:
                return data  # done + cleanup, or a replay: never append twice
            data['messages'].append(message)
            data.pop('pendingTurnId', None)
            data.pop('turnStarted', None)
            if session_key:
                data['sessionKey'] = session_key
            return self._put(db, data)

    def recover(self, jobs_dir):
        """Single Web-process startup: keep partial output after an interrupted run."""
        for data in self.list():
            turn = data.get('pendingTurnId')
            if not turn:
                continue
            text, thinking, activity = '', '', []
            finished = False
            path = jobs_dir / f'{turn}.jsonl'
            if path.is_file():
                for line in path.read_text(encoding='utf-8').splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    value = event.get('data')
                    if event['event'] == 'token' and isinstance(value, str):
                        text += value
                    elif event['event'] == 'thinking' and isinstance(value, str):
                        thinking = (thinking + value)[-4000:]
                    elif event['event'] == 'activity' and isinstance(value, str):
                        activity.append(value)
                    elif event['event'] == 'error':
                        text += f'\n\nError: {value}'
                        finished = True
                    elif event['event'] == 'done':
                        finished = True
            if not finished:
                text += '\n\n（服务重启，本轮已中断。可以重试上一条消息。）'
            self.finish(data['id'], turn, {'role': 'assistant', 'content': text or '（无输出）',
                                         'thinking': thinking, 'activity': '\n'.join(activity)})
