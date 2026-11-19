"""Access public Zhihu user and article data with a small Python API."""

from typing import Any

from .client import ZhihuClient, extract_article_id, extract_member_identifier
from .errors import (
    ZhihuAPIError,
    ZhihuConnectionError,
    ZhihuError,
    ZhihuNotFoundError,
    ZhihuRateLimitError,
    ZhihuReaderError,
    ZhihuResponseError,
)
from .models import ArticleInfo, ColumnInfo, UserIdentity, UserRef

__version__ = "0.2.0"

__all__ = [
    "ArticleInfo",
    "ColumnInfo",
    "UserIdentity",
    "UserRef",
    "ZhihuAPIError",
    "ZhihuClient",
    "ZhihuConnectionError",
    "ZhihuError",
    "ZhihuNotFoundError",
    "ZhihuRateLimitError",
    "ZhihuReaderError",
    "ZhihuResponseError",
    "extract_article_id",
    "extract_member_identifier",
    "get_article",
    "get_url_token",
    "get_user_id",
]


def get_user_id(url_token: str, **kwargs: Any) -> str:
    """Convenience wrapper around :meth:`ZhihuClient.get_user_id`."""
    return ZhihuClient(**kwargs).get_user_id(url_token)


def get_url_token(user_id: str, **kwargs: Any) -> str:
    """Convenience wrapper around :meth:`ZhihuClient.get_url_token`."""
    return ZhihuClient(**kwargs).get_url_token(user_id)


def get_article(article_id: str, **kwargs: Any) -> ArticleInfo:
    """Convenience wrapper around :meth:`ZhihuClient.get_article`."""
    return ZhihuClient(**kwargs).get_article(article_id)
