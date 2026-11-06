"""Rich feed presentation adapter over the upstream collector registry and service.

The compatibility endpoints only group/format data; collection, XML parsing,
limits, ETags and cache ownership all live in easel.trends.
"""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter

from easel.direct_api import read_settings
from easel.trends.protocol import MAX_ITEMS, timestamp
from easel.trends.service import TrendService
from easel.trends.sources import load_sources

SOURCES = {"x": "X", "reddit": "Reddit", "news": "海外资讯"}


def _epoch(value: str | None) -> int | None:
    return int(timestamp(value)) if value else None


def present(group: dict, sources: dict[str, str], source_map: dict[str, str]) -> dict:
    items = []
    for item in group.get("items", []):
        metadata = item.get("rss", {})
        source = source_map.get(metadata.get("source"))
        if source is None or not item["url"]:
            continue
        items.append({"id": item["id"], "title": item["title"], "url": item["url"],
                      "source": source, "publisher": metadata.get("publisher", ""),
                      "author": metadata.get("author", ""), "summary": metadata.get("summary", ""),
                      "published_at": _epoch(item.get("published_at")),
                      "heat_score": metadata.get("heat_score"), "metrics": metadata.get("metrics", {})})
    return {"configured": bool(group), "error": (group.get("error") or {}).get("message", ""),
            "error_code": (group.get("error") or {}).get("code", ""),
            "stale": bool(group.get("stale")), "fetched_at": _epoch(group.get("fetched_at")),
            "feed_updated_at": _epoch(group.get("feed_updated_at")),
            "groups": [{"source": key, "label": label, "items": [item for item in items if item["source"] == key]}
                       for key, label in sources.items()]}


def create_router(env_file: Path, service: TrendService | None = None) -> APIRouter:
    router = APIRouter()
    service = service if service is not None else TrendService()

    def get(identifier: str, sources: dict[str, str], source_map: dict[str, str]) -> dict:
        try:
            environment = read_settings(env_file)
            registry = {source.id: source for source in load_sources(env_file.parent, environment, warnings=[])}
            source = registry.get(identifier)
            group = service.get(source, environment, MAX_ITEMS) if source else {}
            return present(group, sources, source_map)
        except Exception:
            result = present({}, sources, source_map)
            result["error"] = "订阅配置暂时无法读取，请检查本机数据源配置。"
            return result

    @router.get("/api/overseas-trends")
    def overseas_trends():
        return get("overseas-rss", SOURCES, {key: key for key in SOURCES})

    @router.get("/api/ithome-trends")
    def ithome_trends():
        return get("ithome-rss", {"ithome": "IT之家"}, {"news": "ithome"})

    return router
