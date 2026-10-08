"""Environment checks must describe the runtime used by the web service."""
import asyncio
import io
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(ROOT / "skills/shared/scripts"))
import app as web
import install_tool


def test_web_check_uses_runtime_and_remotion_directory(monkeypatch):
    def run(argv, **kwargs):
        assert argv[argv.index("--python") + 1] == sys.executable
        directory = Path(argv[argv.index("--dir") + 1])
        assert (directory / "package.json").is_file()
        return SimpleNamespace(returncode=0, stdout=json.dumps({"tools": []}))

    monkeypatch.setattr(web.subprocess, "run", run)
    monkeypatch.setattr(web, "_ENV_TOOLS_CACHE", {"ts": 0, "data": None})
    asyncio.run(web.api_env_tools(refresh=True))


def test_web_install_uses_same_runtime_and_directory(monkeypatch):
    done = threading.Event()

    def popen(argv, **kwargs):
        try:
            assert argv[argv.index("--python") + 1] == sys.executable
            assert (Path(argv[argv.index("--dir") + 1]) / "package.json").is_file()
            return SimpleNamespace(stdout=io.StringIO('{"results":[{"state":"ok"}]}'),
                                   stderr=io.StringIO(), wait=lambda **kw: 0)
        finally:
            done.set()

    monkeypatch.setattr(web, "_install_tool_ids", lambda: {"rmdeps"})
    monkeypatch.setattr(web.subprocess, "Popen", popen)
    monkeypatch.setattr(web, "_ENV_JOBS", {})
    result = asyncio.run(web.api_env_install(web.EnvInstallRequest(id="rmdeps")))
    assert done.wait(5)
    # Assertion failures in the background runner become failed jobs.
    for thread in threading.enumerate():
        if thread.name.endswith("(_run)"):
            thread.join(5)
    assert web._ENV_JOBS[result["jobId"]]["state"] == "ok"


def fake_playwright(tmp_path, monkeypatch):
    package = tmp_path / "playwright"
    package.mkdir()
    (package / "__init__.py").write_text("")
    binary = tmp_path / "Google Chrome for Testing"
    (package / "sync_api.py").write_text(
        "from types import SimpleNamespace\n"
        "from contextlib import contextmanager\n"
        "@contextmanager\ndef sync_playwright():\n"
        f" yield SimpleNamespace(chromium=SimpleNamespace(executable_path={str(binary)!r}))\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    return binary


def test_playwright_requires_browser_binary(tmp_path, monkeypatch):
    binary = fake_playwright(tmp_path, monkeypatch)
    tool = next(t for t in install_tool.TOOLS if t.id == "pw")
    assert install_tool.check_tool(tool, sys.executable)["state"] == "missing"
    binary.touch()
    assert install_tool.check_tool(tool, sys.executable)["state"] == "ok"


def test_cft_finds_playwright_browser_on_macos(tmp_path, monkeypatch):
    binary = fake_playwright(tmp_path, monkeypatch)
    binary.touch()
    tool = next(t for t in install_tool.TOOLS if t.id == "cft")
    assert install_tool.check_tool(tool, sys.executable)["state"] == "ok"


def test_headless_shell_directory_is_not_installed_binary(tmp_path):
    cache = tmp_path / "node_modules/.remotion/chrome-headless-shell/mac-arm64"
    cache.mkdir(parents=True)
    tool = next(t for t in install_tool.TOOLS if t.id == "shell")
    assert install_tool.check_tool(tool, sys.executable, str(tmp_path))["state"] == "missing"
    (cache / "chrome-headless-shell").touch()
    assert install_tool.check_tool(tool, sys.executable, str(tmp_path))["state"] == "ok"
