from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time
from typing import Any

import requests

from .models import Palette


LOSPEC_BASE = "https://lospec.com"
LOSPEC_API = "https://api.lospec.com"
CACHE_VERSION = 1


class LospecError(RuntimeError):
    pass


class LospecClient:
    def __init__(self, timeout: float = 12.0, cache_path: str | Path | None = None) -> None:
        self.timeout = timeout
        self.cache_path = Path(cache_path) if cache_path else Path.home() / ".colorutils" / "lospec_cache.json"
        self.cache = self._load_cache()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "ColorUtils/0.1 (+https://lospec.com)",
                "Accept": "application/json, text/plain, */*",
            }
        )

    def list_palettes(
        self,
        *,
        page: int = 0,
        sorting_type: str = "default",
        color_filter_type: str = "any",
        color_number: int = 8,
        tag: str = "",
        refresh: bool = False,
    ) -> tuple[list[Palette], int]:
        cache_key = self._list_cache_key(page, sorting_type, color_filter_type, color_number, tag)
        if not refresh:
            cached = self.cache.get("list_pages", {}).get(cache_key)
            if cached:
                palettes = [Palette.from_dict(item) for item in cached.get("palettes", [])]
                return palettes, int(cached.get("totalCount") or 0)

        params = {
            "colorNumberFilterType": color_filter_type,
            "colorNumber": str(color_number),
            "page": str(page),
            "tag": tag,
            "sortingType": sorting_type,
        }
        headers = {"X-Requested-With": "XMLHttpRequest"}
        data = self._get_json(f"{LOSPEC_BASE}/palette-list/load", params=params, headers=headers)
        palettes = [self._parse_palette(item) for item in data.get("palettes", [])]
        self.cache.setdefault("list_pages", {})[cache_key] = {
            "palettes": [palette.to_dict() for palette in palettes],
            "totalCount": int(data.get("totalCount") or 0),
            "cachedAt": time.time(),
        }
        for palette in palettes:
            if palette.slug:
                self.cache.setdefault("palettes", {})[palette.slug] = {
                    **palette.to_dict(),
                    "cachedAt": time.time(),
                }
        self._save_cache()
        return palettes, int(data.get("totalCount") or 0)

    def suggest(self, query: str, *, limit: int = 24, refresh: bool = False) -> list[dict[str, str]]:
        query = query.strip()
        if not query:
            return []
        cache_key = query.lower()
        if not refresh:
            cached = self.cache.get("suggestions", {}).get(cache_key)
            if cached:
                return cached[:limit]
        data = self._get_json(f"{LOSPEC_API}/palettes/suggest/{query}")
        suggestions = data.get("data", data)
        result: list[dict[str, str]] = []
        for item in suggestions[:limit]:
            title = str(item.get("title", "")).strip()
            slug = str(item.get("slug", "")).strip()
            if title and slug:
                result.append({"title": title, "slug": slug})
        self.cache.setdefault("suggestions", {})[cache_key] = result
        self._save_cache()
        return result

    def search_palettes(self, query: str, *, limit: int = 24, refresh: bool = False) -> list[Palette]:
        suggestions = self.suggest(query, limit=limit, refresh=refresh)
        if not suggestions:
            return []
        palettes: list[Palette] = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_map = {
                executor.submit(self.get_palette, item["slug"], fallback_title=item["title"], refresh=refresh): item
                for item in suggestions
            }
            for future in as_completed(future_map):
                try:
                    palettes.append(future.result())
                except Exception:
                    item = future_map[future]
                    palettes.append(Palette(title=item["title"], slug=item["slug"], colors=()))
        order = {item["slug"]: index for index, item in enumerate(suggestions)}
        palettes.sort(key=lambda palette: order.get(palette.slug, 9999))
        return [palette for palette in palettes if palette.colors]

    def get_palette(self, slug: str, *, fallback_title: str = "", refresh: bool = False) -> Palette:
        if not refresh:
            cached = self.cache.get("palettes", {}).get(slug)
            if cached and cached.get("colors"):
                return Palette.from_dict(cached)
        data = self._get_json(f"{LOSPEC_BASE}/palette-list/{slug}.json")
        title = str(data.get("name") or data.get("title") or fallback_title or slug)
        author = str(data.get("author") or "")
        colors = tuple(self._normalize_hex(value) for value in data.get("colors", []) if value)
        palette = Palette(title=title, slug=slug, colors=colors, author=author)
        self.cache.setdefault("palettes", {})[slug] = {**palette.to_dict(), "cachedAt": time.time()}
        self._save_cache()
        return palette

    def _get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise LospecError(f"Lospec request failed: {exc}") from exc
        except ValueError as exc:
            raise LospecError("Lospec returned invalid JSON") from exc

    def _parse_palette(self, item: dict[str, Any]) -> Palette:
        user = item.get("user") or {}
        colors = item.get("colorsArray") or item.get("colors") or []
        return Palette(
            title=str(item.get("title") or item.get("name") or item.get("slug") or "Untitled").strip(),
            slug=str(item.get("slug") or "").strip(),
            colors=tuple(self._normalize_hex(value) for value in colors if value),
            author=str(user.get("name") or item.get("author") or "").strip(),
            downloads=str(item.get("downloads") or ""),
            likes=item.get("likes") if isinstance(item.get("likes"), int) else None,
            tags=tuple(str(tag).strip() for tag in item.get("tags", []) if str(tag).strip()),
        )

    @staticmethod
    def _normalize_hex(value: str) -> str:
        value = value.strip().lstrip("#")
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        return value.lower()

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return self._empty_cache()
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._empty_cache()
        if data.get("version") != CACHE_VERSION:
            return self._empty_cache()
        data.setdefault("list_pages", {})
        data.setdefault("palettes", {})
        data.setdefault("suggestions", {})
        return data

    def _save_cache(self) -> None:
        self.cache["version"] = CACHE_VERSION
        self.cache["savedAt"] = time.time()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.cache_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.cache_path)

    @staticmethod
    def _empty_cache() -> dict[str, Any]:
        return {"version": CACHE_VERSION, "list_pages": {}, "palettes": {}, "suggestions": {}}

    @staticmethod
    def _list_cache_key(
        page: int,
        sorting_type: str,
        color_filter_type: str,
        color_number: int,
        tag: str,
    ) -> str:
        return "|".join(
            [
                f"page={page}",
                f"sort={sorting_type}",
                f"filter={color_filter_type}",
                f"colors={color_number}",
                f"tag={tag.lower().strip()}",
            ]
        )
