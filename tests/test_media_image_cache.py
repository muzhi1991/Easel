"""Mutable generated images must not retain login QR snapshots in HTTP caches."""
import asyncio
import ast
from pathlib import Path

from starlette.responses import FileResponse
import pytest


@pytest.mark.parametrize('name', ['_login/wechat-oa-mp.png', 'project/登录二维码.png', 'project/photo.jpg'])
def test_media_images_disable_caching(tmp_path, name):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'web/app.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'api_media')
    fn.decorator_list = []
    env = {'FileResponse': FileResponse, '_safe_output_path': lambda path: tmp_path / path,
           'IMAGE_EXTS': {'.png', '.jpg'}}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'api_media', 'exec'), env)
    for download in [False, True]:
        response = asyncio.run(env['api_media'](name, download=download))
        assert 'no-store' in response.headers.get('cache-control', '')
