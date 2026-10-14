import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/shared/scripts'))
spec = importlib.util.spec_from_file_location('ecom_images', ROOT / 'skills/builtin/ecom-details-image/scripts/generate_image.py')
ecom = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecom)


def test_prompt_file_reference_and_options_forwarded(tmp_path, monkeypatch):
    prompt = tmp_path / 'prompt.txt'; prompt.write_text(' 保留陶瓷杯，换背景 ')
    calls = []
    monkeypatch.setattr(ecom.ai_image, 'main', lambda a: calls.append(ecom.ai_image.parse_args(a)))
    ecom.main(['--prompt-file', str(prompt), '--image', 'cup.png', '--mask', 'mask.png',
               '--provider', 'sunburst', '--size', '2:3', '--quality', 'high', '--n', '2',
               '--timeout', '300', '--format', 'webp', '--output-dir', 'outputs/陶瓷杯主图'])
    a = calls[0]
    assert a.command == 'img2img' and a.prompt == '保留陶瓷杯，换背景'
    assert (a.image, a.mask, a.provider, a.quality, a.n, a.timeout) == ('cup.png', 'mask.png', 'sunburst', 'high', 2, 300)
    assert a.size == '1024x1536' and a.output.endswith('.webp')


def test_default_and_rerun_preserve_unique_outputs(monkeypatch):
    calls = []
    monkeypatch.setattr(ecom.ai_image, 'main', lambda a: calls.append(ecom.ai_image.parse_args(a)))
    ecom.main(['--prompt', 'cup']); ecom.main(['--prompt', 'cup'])
    assert calls[0].provider is None and calls[0].timeout is None
    assert calls[0].command == 'text2img' and calls[0].size == '1024x1024'
    assert calls[0].output != calls[1].output


@pytest.mark.parametrize('argv', [['--prompt', ' '], ['--prompt', 'cup', '--n', '0'], ['--prompt', 'cup', '--mask', 'm.png']])
def test_invalid_input_never_submits(argv, monkeypatch):
    monkeypatch.setattr(ecom.ai_image, 'main', lambda a: pytest.fail('must not submit'))
    with pytest.raises(SystemExit): ecom.main(argv)


def test_real_unified_entry_resolves_default_and_rejects_qwen_edit(tmp_path, monkeypatch):
    import output_paths
    import easel.media
    from easel_media_adapters import MediaRuntime
    monkeypatch.setattr(output_paths, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(output_paths, 'OUTPUTS_DIR', tmp_path / 'outputs')
    monkeypatch.setenv('EASEL_MEDIA_CONFIG', str(tmp_path / 'media.json'))
    rt = MediaRuntime()
    for name, edit in [('flare', True), ('qwen', False)]:
        rt.save_provider({'id': name, 'name': name, 'adapter': 'openai-image', 'settings': {
            'base_url': 'https://test.invalid/v1', 'model': name, 'supports_edit': edit}}, ['image'] if name == 'flare' else [])
    seen = []
    from easel_media_adapters.image import OpenAIImageAdapter
    actual = OpenAIImageAdapter.submit
    def submit(self, provider, capability, request):
        if provider['id'] == 'qwen': return actual(self, provider, capability, request)
        seen.append((provider['id'], request))
        return {'outputs': [str(request.output)], 'provider': provider['id']}
    monkeypatch.setattr(OpenAIImageAdapter, 'submit', submit)
    ecom.main(['--prompt', 'cup', '--image', 'cup.png'])
    assert seen[0][0] == 'flare' and seen[0][1].image == Path('cup.png')
    with pytest.raises(SystemExit): ecom.main(['--prompt', 'cup', '--image', 'cup.png', '--provider', 'qwen'])
    assert len(seen) == 1
    with pytest.raises(SystemExit): ecom.main(['--prompt', 'cup', '--output-dir', '/tmp/outside-project'])
    assert len(seen) == 1
