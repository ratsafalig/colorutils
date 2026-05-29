from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Palette:
    title: str
    slug: str
    colors: tuple[str, ...]
    author: str = ""
    downloads: str = ""
    likes: int | None = None
    tags: tuple[str, ...] = ()

    @property
    def color_count(self) -> int:
        return len(self.colors)

    @property
    def display_name(self) -> str:
        author = f" - {self.author}" if self.author else ""
        return f"{self.title}{author}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "slug": self.slug,
            "colors": list(self.colors),
            "author": self.author,
            "downloads": self.downloads,
            "likes": self.likes,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Palette":
        return cls(
            title=str(data.get("title") or data.get("name") or data.get("slug") or "Untitled"),
            slug=str(data.get("slug") or ""),
            colors=tuple(str(color).strip().lstrip("#").lower() for color in data.get("colors", []) if color),
            author=str(data.get("author") or ""),
            downloads=str(data.get("downloads") or ""),
            likes=data.get("likes") if isinstance(data.get("likes"), int) else None,
            tags=tuple(str(tag) for tag in data.get("tags", []) if tag),
        )
