from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class UserIdentity:
    """The public identifiers of a Zhihu user."""

    id: str
    url_token: str
    name: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "url_token": self.url_token, "name": self.name}


@dataclass(frozen=True)
class UserRef:
    """A user reference embedded in an article or column response."""

    id: Optional[str] = None
    url_token: Optional[str] = None
    name: Optional[str] = None

    @property
    def display_name(self) -> Optional[str]:
        return self.name or self.url_token or self.id

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "url_token": self.url_token,
            "name": self.name,
            "display_name": self.display_name,
        }


@dataclass(frozen=True)
class ColumnInfo:
    """Metadata of the column that contains an article."""

    id: Optional[str] = None
    title: Optional[str] = None
    url_token: Optional[str] = None
    author: Optional[UserRef] = None
    created: Optional[int] = None

    @property
    def created_at(self) -> Optional[datetime]:
        return _to_datetime(self.created)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url_token": self.url_token,
            "author": self.author.as_dict() if self.author else None,
            "created": self.created,
            "created_at": _to_isoformat(self.created_at),
        }


@dataclass(frozen=True)
class ArticleInfo:
    """Metadata of a Zhihu column article."""

    id: str
    title: Optional[str] = None
    author: UserRef = UserRef()
    column: Optional[ColumnInfo] = None
    created: Optional[int] = None
    updated: Optional[int] = None
    time_text: Optional[str] = None
    time_kind: Optional[str] = None
    source: str = "direct"
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def published_at(self) -> Optional[datetime]:
        """Article publication time as a timezone-aware UTC datetime."""
        return _to_datetime(self.created)

    @property
    def updated_at(self) -> Optional[datetime]:
        """Last-modified time as a timezone-aware UTC datetime."""
        return _to_datetime(self.updated)

    @property
    def column_title(self) -> Optional[str]:
        return self.column.title if self.column else None

    @property
    def column_author(self) -> UserRef:
        if self.column and self.column.author:
            return self.column.author
        return self.author

    @property
    def author_name(self) -> Optional[str]:
        return self.author.display_name

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "column_title": self.column_title,
            "author": self.column_author.as_dict(),
            "published_at": _to_isoformat(self.published_at),
            "updated_at": _to_isoformat(self.updated_at),
            "created": self.created,
            "updated": self.updated,
            "time_text": self.time_text,
            "time_kind": self.time_kind,
            "source": self.source,
            "column": self.column.as_dict() if self.column else None,
        }


def _to_datetime(timestamp: Optional[int]) -> Optional[datetime]:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _to_isoformat(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None
