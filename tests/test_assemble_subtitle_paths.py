"""Render actual subtitles from paths containing filtergraph metacharacters."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def has_subtitles():
    return shutil.which('ffmpeg') and ' subtitles ' in subprocess.run(
        ['ffmpeg', '-filters'], capture_output=True, text=True).stdout


@pytest.mark.skipif(not has_subtitles(), reason='requires ffmpeg built with libass')
def test_real_subtitles_handle_special_paths_and_relative_output(tmp_path):
    project = tmp_path / 'outputs' / "中文 'quote,[bracket];colon: space"
    project.mkdir(parents=True)
    image = project / 'source.ppm'
    image.write_bytes(b'P6\n32 32\n255\n' + bytes([100, 0, 0]) * 1024)
    subtitle = project / "caption's,[1];.srt"
    subtitle.write_text('1\n00:00:00,000 --> 00:00:00,400\nSubtitle path test\n')
    storyboard = project / 'storyboard.json'
    storyboard.write_text(json.dumps({'size': '160x160', 'image_motion': 'static',
        'subtitle': str(subtitle), 'shots': [{'image': str(image), 'duration': 0.4}]}))
    output = (project / 'final.mp4').relative_to(tmp_path)
    script = Path(__file__).resolve().parents[1] / 'skills/builtin/auto-short-video/scripts/assemble.py'
    result = subprocess.run([sys.executable, str(script), 'assemble', '--resume', '--storyboard',
                             str(storyboard), '-o', str(output)], cwd=tmp_path,
        env={**os.environ, 'EASEL_ROOT': str(tmp_path)}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / output).stat().st_size > 0
