"""Self-hosted RSS channel, deliberately independent of the upstream trend sources."""
from __future__ import annotations

import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from fastapi import APIRouter

from easel.direct_api import read_settings
from easel.timeouts import TIMEOUT_TREND_FEED

SOURCES = {"x": "X", "reddit": "Reddit", "news": "海外资讯"}
CACHE_SECONDS = 300
RETRY_SECONDS = 60
MAX_FEED_BYTES = 2 * 1024 * 1024
METRICS = ("impressions", "likes", "reposts", "replies", "quotes", "reddit_rank", "source_weight")


def _text(node: ET.Element, name: str) -> str:
    return (node.findtext(name) or "").strip()


def _timestamp(value: str) -> int | None:
    try:
        dt = parsedate_to_datetime(value)
        return int(dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp())
    except (ValueError, TypeError, OverflowError):
        return None


def _number(value: str) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except ValueError:
        return None


def parse_feed(body: bytes, source_map: dict[str, str] | None = None) -> tuple[list[dict], int | None]:
    if len(body) > MAX_FEED_BYTES or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Invalid RSS document")
    channel = ET.fromstring(body).find("channel")
    if channel is None:
        raise ValueError("RSS channel missing")
    source_map = source_map if source_map is not None else {key: key for key in SOURCES}
    items, seen = [], set()
    for node in channel.findall("item"):
        source, title, url = _text(node, "source"), _text(node, "title"), _text(node, "link")
        identity = _text(node, "guid") or url
        if source not in source_map or not title or not url.startswith(("https://", "http://")):
            continue
        if identity in seen:
            continue
        seen.add(identity)
        metrics = {}
        for key in METRICS:
            value = _number(_text(node, f"heat/{key}"))
            if value is not None:
                metrics[key] = value
        items.append({
            "id": identity, "source": source_map[source], "title": title, "url": url,
            "publisher": _text(node, "publisher"), "author": _text(node, "author"),
            "summary": _text(node, "description"), "published_at": _timestamp(_text(node, "pubDate")),
            "heat_score": _number(_text(node, "heat/heat_score")), "metrics": metrics,
        })
    return items, _timestamp(_text(channel, "lastBuildDate"))


class OverseasFeed:
    """One subscription cache shared by its source cards and concurrent requests."""

    def __init__(self, env_file: Path, *, config_key: str = "EASEL_OVERSEAS_RSS_URL",
                 sources: dict[str, str] | None = None, source_map: dict[str, str] | None = None):
        self.env_file = env_file
        self.config_key = config_key
        self.sources = dict(SOURCES if sources is None else sources)
        self.source_map = dict(source_map if source_map is not None else {key: key for key in self.sources})
        self._lock = threading.Lock()
        self._url = ""
        self._items: list[dict] = []
        self._feed_updated_at: int | None = None
        self._fetched_at = 0
        self._checked_at = 0.0
        self._etag = ""
        self._error = ""

    def _download(self, url: str, settings: dict[str, str]) -> tuple[bytes, str] | None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid feed URL")
        headers = {"User-Agent": "Easel-RSS/1.0", "Accept": "application/rss+xml, application/xml, text/xml, text/plain"}
        if self._etag:
            headers["If-None-Match"] = self._etag
        proxy = settings.get("EASEL_PROXY", "").strip()
        opener = urllib.request.build_opener(*([urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []))
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_TREND_FEED) as response:
                body = response.read(MAX_FEED_BYTES + 1)
                # Commit the validator only after parsing succeeds in get().
                return body, response.headers.get("ETag", "")
        except urllib.error.HTTPError as error:
            if error.code == 304 and self._fetched_at:
                return None
            raise

    def get(self) -> dict:
        with self._lock:
            settings = read_settings(self.env_file)
            url = settings.get(self.config_key, "").strip()
            if url != self._url:
                self._url, self._items, self._etag = url, [], ""
                self._fetched_at, self._checked_at, self._feed_updated_at, self._error = 0, 0, None, ""
            now = time.time()
            if url and now - self._checked_at >= (RETRY_SECONDS if self._error else CACHE_SECONDS):
                try:
                    downloaded = self._download(url, settings)
                    if downloaded is not None:
                        body, etag = downloaded
                        items, feed_updated_at = parse_feed(body, self.source_map)
                        self._items, self._feed_updated_at, self._etag = items, feed_updated_at, etag
                    self._fetched_at, self._error = int(time.time()), ""
                except Exception:
                    # Never return upstream bodies, URLs or credentials to the browser.
                    self._error = "订阅暂时无法更新，请稍后刷新。"
                self._checked_at = time.time()
            return {
                "configured": bool(url), "error": self._error,
                "stale": bool(self._error and self._fetched_at),
                "fetched_at": self._fetched_at or None, "feed_updated_at": self._feed_updated_at,
                "groups": [{"source": key, "label": label,
                            "items": [item for item in self._items if item["source"] == key]}
                           for key, label in self.sources.items()],
            }


def create_router(env_file: Path) -> APIRouter:
    router = APIRouter()
    feed = OverseasFeed(env_file)

    @router.get("/api/overseas-trends")
    def overseas_trends():
        return feed.get()

    ithome_feed = OverseasFeed(env_file, config_key="EASEL_ITHOME_RSS_URL",
                               sources={"ithome": "IT之家"}, source_map={"news": "ithome"})

    @router.get("/api/ithome-trends")
    def ithome_trends():
        return ithome_feed.get()

    return router
