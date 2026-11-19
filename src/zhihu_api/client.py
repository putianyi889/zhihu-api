import json
import re
import time
from http.cookiejar import CookieJar
from typing import Any, Dict, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .errors import (
    ZhihuAPIError,
    ZhihuConnectionError,
    ZhihuNotFoundError,
    ZhihuRateLimitError,
    ZhihuResponseError,
)
from .models import ArticleInfo, ColumnInfo, UserIdentity, UserRef

DEFAULT_BASE_URL = "https://www.zhihu.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
MEMBER_INCLUDE = "id,url_token,name"
ARTICLE_INCLUDE = "created,updated,title,author,url,column"

_MEMBER_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ARTICLE_ID_RE = re.compile(r"^\d+$")
_MEMBER_PATH_RE = re.compile(r"/(?:people|api/v4/members)/([^/]+)/?$")
_ARTICLE_PATH_RE = re.compile(r"/(?:p|article)/(\d+)/?$")


class ZhihuClient:
    """A small client for Zhihu's public web APIs.

    The client only reads public data. If Zhihu asks for verification, pass a
    browser cookie string via ``cookie`` (for example ``"z_c0=...;"``).
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        cookie: Optional[str] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Any = None,
        retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cookie = cookie
        self.user_agent = user_agent
        self.retries = max(0, retries)
        self._opener = opener or build_opener(HTTPCookieProcessor(CookieJar()))

    def get_user(self, identifier: str) -> UserIdentity:
        """Resolve either a url_token or a user id to both identifiers."""
        value = extract_member_identifier(identifier)
        payload = self._get_json(
            "/api/v4/members/" + quote(value, safe=""),
            params={"include": MEMBER_INCLUDE},
        )
        user_id = _string(payload.get("id"))
        url_token = _string(payload.get("url_token"))
        if not user_id or not url_token:
            raise ZhihuResponseError(
                "Member response does not contain both 'id' and 'url_token'",
                url=self.base_url + "/api/v4/members/" + value,
            )
        return UserIdentity(
            id=user_id,
            url_token=url_token,
            name=_string(payload.get("name")),
        )

    def get_user_id(self, url_token: str) -> str:
        """Return the Zhihu user id for a url_token or profile URL."""
        return self.get_user(url_token).id

    def get_url_token(self, user_id: str) -> str:
        """Return the url_token for a Zhihu user id."""
        return self.get_user(user_id).url_token

    def get_article(self, article_id: str) -> ArticleInfo:
        """Return metadata for a column article id or article URL."""
        value = extract_article_id(article_id)
        url = "/api/v4/articles/" + value
        payload = self._get_json(url, params={"include": ARTICLE_INCLUDE})

        response_id = _string(payload.get("id"))
        if response_id and response_id != value:
            raise ZhihuResponseError(
                "Article response id does not match requested id: "
                f"expected {value!r}, got {response_id!r}"
            )

        author = _parse_user_ref(payload.get("author"))
        column = _parse_column(payload.get("column"))
        created = _timestamp(payload.get("created"))
        updated = _timestamp(payload.get("updated"))

        return ArticleInfo(
            id=response_id or value,
            title=_string(payload.get("title")),
            author=author,
            column=column,
            created=created,
            updated=updated,
            raw=payload,
        )

    def _get_json(
        self, path: str, params: Optional[Mapping[str, str]] = None
    ) -> Dict[str, Any]:
        url = self.base_url + path
        if params:
            url += "?" + urlencode(params, safe=",")

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.base_url + "/",
            "User-Agent": self.user_agent,
            "X-Requested-With": "fetch",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie

        for attempt in range(self.retries + 1):
            request = Request(url, headers=headers)
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    body = response.read()
                    status = getattr(response, "status", None) or getattr(
                        response, "code", 200
                    )
            except HTTPError as exc:
                body = exc.read() if hasattr(exc, "read") else b""
                status = exc.code
                if status in (429, 503) and attempt < self.retries:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise _api_error_from_body(body, status, url) from exc
            except URLError as exc:
                raise ZhihuConnectionError(
                    f"Failed to connect to Zhihu: {exc.reason}", url=url
                ) from exc

            payload = _parse_json(body, url)
            if status >= 400:
                raise _api_error_from_payload(payload, status, url)
            if isinstance(payload, dict) and "error" in payload:
                raise _api_error_from_payload(payload, status, url)
            if not isinstance(payload, dict):
                raise ZhihuResponseError(
                    f"Expected a JSON object from {url!r}, got {type(payload).__name__}"
                )
            return payload

        raise ZhihuConnectionError(f"Request retries exhausted for {url!r}", url=url)


def extract_member_identifier(value: str) -> str:
    """Accept a raw user id/url_token, profile URL or member API URL."""
    text = str(value).strip()
    if not text:
        raise ValueError("User id or url_token must not be empty")

    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        match = _MEMBER_PATH_RE.search(parsed.path)
        if not match:
            raise ValueError(f"Not a Zhihu user profile URL: {value!r}")
        text = unquote(match.group(1))

    if not _MEMBER_IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"Invalid Zhihu user id or url_token: {value!r}")
    return text


def extract_article_id(value: str) -> str:
    """Accept a numeric article id or a zhuanlan.zhihu.com article URL."""
    text = str(value).strip()
    if not text:
        raise ValueError("Article id must not be empty")

    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        match = _ARTICLE_PATH_RE.search(parsed.path)
        if not match:
            raise ValueError(f"Not a Zhihu article URL: {value!r}")
        return match.group(1)

    if not _ARTICLE_ID_RE.fullmatch(text):
        raise ValueError(f"Invalid Zhihu article id: {value!r}")
    return text


def _parse_json(body: bytes, url: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ZhihuResponseError(f"Invalid JSON returned by {url!r}") from exc


def _api_error_from_body(body: bytes, status: int, url: str) -> ZhihuAPIError:
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    return _api_error_from_payload(payload, status, url)


def _api_error_from_payload(
    payload: Any, status: int, url: str
) -> ZhihuAPIError:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        error = payload if isinstance(payload, dict) else {}

    code = error.get("code")
    message = _string(error.get("message")) or _string(error.get("reason"))
    if not message:
        message = f"Zhihu request failed with HTTP {status}"

    error_class = ZhihuAPIError
    if status == 404 or code in (10003, 404):
        error_class = ZhihuNotFoundError
    elif status == 429 or code in (40352, 429):
        error_class = ZhihuRateLimitError

    return error_class(
        message, status=status, code=code, url=url, payload=payload
    )


def _parse_user_ref(value: Any) -> UserRef:
    if not isinstance(value, dict):
        return UserRef()
    return UserRef(
        id=_string(value.get("id")),
        url_token=_string(value.get("url_token")),
        name=_string(value.get("name")),
    )


def _parse_column(value: Any) -> Optional[ColumnInfo]:
    if not isinstance(value, dict):
        return None
    column_id = _string(value.get("id")) or _string(value.get("url_token"))
    title = _string(value.get("title")) or _string(value.get("name"))
    author = _parse_user_ref(value.get("author"))
    if not any((column_id, title, author.id, author.url_token, author.name)):
        return None
    return ColumnInfo(
        id=column_id,
        title=title,
        url_token=_string(value.get("url_token")),
        author=author if author.display_name or author.id else None,
        created=_timestamp(value.get("created")),
    )


def _string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _timestamp(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = _string(value)
    if text and text.isdigit():
        return int(text)
    return None
