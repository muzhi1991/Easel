"""Verify model routing without contacting Fish or spending credits."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/shared/scripts'))
spec = importlib.util.spec_from_file_location('fish_voice_client', ROOT / 'skills/shared/scripts/voice_clone.py')
voice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(voice)

@pytest.mark.parametrize('env_model,cli_model,expected', [
    ('', None, 's2.1-pro-free'),
    ('s2-pro', None, 's2-pro'),
    ('s2-pro', 's2.1-pro-free', 's2.1-pro-free'),
])
def test_model_header_and_default_voice(monkeypatch, tmp_path, env_model, cli_model, expected):
    monkeypatch.setenv('FISH_API_KEY', 'test-key')
    monkeypatch.setenv('FISH_TTS_MODEL', env_model)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'test-audio'
    send = MagicMock(return_value=response)
    monkeypatch.setattr(voice.urllib.request, 'urlopen', send)
    args = SimpleNamespace(model=cli_model, text='测试', voice_id=None, sample=None)
    voice.clone_fish(args, tmp_path / 'test.mp3')
    req = send.call_args.args[0]
    assert req.get_header('Model') == expected
    assert 'reference_id' not in voice.json.loads(req.data)
    assert (tmp_path / 'test.mp3').read_bytes() == b'test-audio'


def test_unknown_model_never_sent(monkeypatch, tmp_path):
    monkeypatch.setenv('FISH_API_KEY', 'test-key')
    send = MagicMock()
    monkeypatch.setattr(voice.urllib.request, 'urlopen', send)
    with pytest.raises(SystemExit):
        voice.clone_fish(SimpleNamespace(model='s2.1-pro-fre'), tmp_path / 'test.mp3')
    send.assert_not_called()
