import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

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

DEFAULT_BASE_URL = "https://www.zhihu.com"
DEFAULT_READER_BASE_URL = "https://r.jina.ai"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
SOURCE_READER = "reader"
SOURCE_DIRECT = "direct"
MEMBER_INCLUDE = "id,url_token,name"
ARTICLE_INCLUDE = "created,updated,title,author,url,column"

_MEMBER_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ARTICLE_ID_RE = re.compile(r"^\d+$")
_MEMBER_PATH_RE = re.compile(r"/(?:people|api/v4/members)/([^/]+)/?$")
_ARTICLE_PATH_RE = re.compile(r"/(?:p|article)/(\d+)/?$")
_AUTHOR_LINK_RE = re.compile(
    r"\[([^\]\n]+)\]\((?:https?:)?//(?:www\.)?zhihu\.com/(?:people|org)/([^/)\s]+)\)",
    re.IGNORECASE,
)
_COLUMN_LINK_RE = re.compile(
    r"首发于\s*\[([^\]\n]+)\]\((?:https?:)?//(?:www\.)?zhihu\.com/column/([^/)\s]+)\)",
    re.IGNORECASE,
)
_TIME_RE = re.compile(
    r"(发布于|编辑于|更新于)\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)"
)
_DOTTED_DATE_RE = re.compile(r"更新日期[：:]\s*(\d{4})\.(\d{1,2})\.(\d{1,2})")
_CHINA_TZ = timezone(timedelta(hours=8))


class ZhihuClient:
    """Read public Zhihu user and article data.

    By default requests go through a public reader proxy (``source="reader"``)
    so that local IPs blocked by Zhihu's anti-bot checks can still read public
    pages. Set ``source="direct"`` to call Zhihu endpoints from this machine,
    optionally with a browser cookie.
    """

    def __init__(
        self,
        *,
        source: str = SOURCE_READER,
        base_url: str = DEFAULT_BASE_URL,
        reader_base_url: str = DEFAULT_READER_BASE_URL,
        reader_api_key: Optional[str] = None,
        timeout: float = 15.0,
        cookie: Optional[str] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Any = None,
        retries: int = 2,
    ) -> None:
        if source not in (SOURCE_READER, SOURCE_DIRECT):
            raise ValueError(f"Unsupported source: {source!r}")
        self.source = source
        self.base_url = base_url.rstrip("/")
        self.reader_base_url = reader_base_url.rstrip("/")
        self.reader_api_key = reader_api_key or os.environ.get("JINA_API_KEY")
        self.timeout = timeout
        self.cookie = cookie
        self.user_agent = user_agent
        self.retries = max(0, retries)
        self._opener = opener or build_opener(HTTPCookieProcessor(CookieJar()))

    def get_user(self, identifier: str) -> UserIdentity:
        """Resolve either a url_token or a user id to both identifiers."""
        value = extract_member_identifier(identifier)
        query = "?" + urlencode({"include": MEMBER_INCLUDE}, safe=",")
        path = "/api/v4/members/" + quote(value, safe="")
        target = self.base_url + path + query

        if self.source == SOURCE_READER:
            payload = self._reader_inner_json(target)
        else:
            payload = self._get_json(path, params={"include": MEMBER_INCLUDE})

        user_id = _string(payload.get("id"))
        url_token = _string(payload.get("url_token"))
        if not user_id or not url_token:
            raise ZhihuResponseError(
                "Member response does not contain both 'id' and 'url_token'",
                url=target,
                payload=payload,
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
        if self.source == SOURCE_READER:
            return self._article_from_reader(value)
        return self._article_from_api(value)

    def _article_from_api(self, value: str) -> ArticleInfo:
        path = "/api/v4/articles/" + value
        payload = self._get_json(path, params={"include": ARTICLE_INCLUDE})
        response_id = _string(payload.get("id"))
        if response_id and response_id != value:
            raise ZhihuResponseError(
                "Article response id does not match requested id: "
                f"expected {value!r}, got {response_id!r}",
                payload=payload,
            )

        return ArticleInfo(
            id=response_id or value,
            title=_string(payload.get("title")),
            author=_parse_user_ref(payload.get("author")),
            column=_parse_column(payload.get("column")),
            created=_timestamp(payload.get("created")),
            updated=_timestamp(payload.get("updated")),
            source=SOURCE_DIRECT,
            raw=payload,
        )

    def _article_from_reader(self, value: str) -> ArticleInfo:
        article_url = self.base_url.replace("www.zhihu.com", "zhuanlan.zhihu.com") + "/p/" + value

        try:
            entity = self._reader_article_entity(article_url, value)
            if entity:
                return _article_from_initial_data(entity, value, article_url)
        except (ZhihuError, ValueError):
            pass

        envelope = self._reader_json(article_url, respond_with="markdown")
        data = envelope.get("data") if isinstance(envelope, dict) else None
        if not isinstance(data, dict):
            raise ZhihuReaderError(f"Reader returned no data for {article_url!r}", url=article_url)

        markdown = _string(data.get("content")) or ""
        if not markdown:
            raise ZhihuReaderError(f"Reader returned empty content for {article_url!r}", url=article_url)

        parsed = _parse_article_markdown(markdown, _string(data.get("title")))
        if not parsed["title"]:
            raise ZhihuResponseError(f"Could not find article title in {article_url!r}", url=article_url)

        time_text, time_kind = "", None
        try:
            time_envelope = self._reader_json(
                article_url, respond_with="markdown", selector=".ContentItem-time"
            )
            time_data = time_envelope.get("data") if isinstance(time_envelope, dict) else {}
            time_text, time_kind = _parse_time_text(
                _string(time_data.get("content")) if isinstance(time_data, dict) else None
            )
        except ZhihuError:
            pass
        if not time_text:
            time_text, time_kind = _parse_time_text(markdown)

        created, updated = _timestamps_from_time_text(time_text, time_kind)

        column = parsed["column"]
        if column and column.url_token:
            column_url = self.base_url + "/column/" + column.url_token
            try:
                column_envelope = self._reader_json(column_url, respond_with="markdown")
                column_data = column_envelope.get("data")
                if isinstance(column_data, dict):
                    column_markdown = _string(column_data.get("content")) or ""
                    column_info = _parse_column_markdown(
                        column_markdown,
                        _string(column_data.get("title")) or column.title,
                        column.url_token,
                    )
                    if column_info:
                        column = column_info
            except ZhihuError:
                pass

        return ArticleInfo(
            id=value,
            title=parsed["title"],
            author=parsed["author"],
            column=column,
            created=created,
            updated=updated,
            time_text=time_text or None,
            time_kind=time_kind,
            source=SOURCE_READER,
            raw={
                "article_url": article_url,
                "time_text": time_text or None,
                "time_kind": time_kind,
            },
        )

    def _reader_article_entity(
        self, article_url: str, article_id: str
    ) -> Optional[Dict[str, Any]]:
        envelope = self._reader_json(
            article_url,
            respond_with="text",
            selector="script#js-initialData",
        )
        data = envelope.get("data") if isinstance(envelope, dict) else None
        script = _string(data.get("text")) or _string(data.get("content")) if isinstance(data, dict) else None
        if not script:
            return None

        state = _parse_json(script.encode("utf-8"), article_url)
        if not isinstance(state, dict):
            return None
        articles = (
            state.get("initialState", {})
            .get("entities", {})
            .get("articles", {})
        )
        if not isinstance(articles, dict):
            return None
        entity = articles.get(article_id)
        return entity if isinstance(entity, dict) else None

    def _reader_inner_json(self, target_url: str) -> Dict[str, Any]:
        envelope = self._reader_json(target_url)
        data = envelope.get("data") if isinstance(envelope, dict) else None
        content = _string(data.get("content")) if isinstance(data, dict) else None
        if not content:
            raise ZhihuReaderError(f"Reader returned no content for {target_url!r}", url=target_url)

        payload = _parse_json(content.encode("utf-8"), target_url)
        if not isinstance(payload, dict):
            raise ZhihuResponseError(f"Expected JSON object from {target_url!r}")
        if "error" in payload:
            raise _api_error_from_payload(payload, 400, target_url)
        return payload

    def _reader_json(
        self,
        target_url: str,
        *,
        respond_with: Optional[str] = None,
        selector: Optional[str] = None,
    ) -> Dict[str, Any]:
        target = re.sub(r"^https?://", "", target_url)
        url = f"{self.reader_base_url}/http://{target}"
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if respond_with:
            headers["x-respond-with"] = respond_with
        if selector:
            headers["x-target-selector"] = selector
        if self.reader_api_key:
            headers["Authorization"] = "Bearer " + self.reader_api_key

        body, status = self._request(url, headers)
        payload = _parse_json(body, url)
        if not isinstance(payload, dict):
            raise ZhihuReaderError(f"Reader returned non-object JSON from {url!r}", url=url)
        code = payload.get("code")
        http_status = payload.get("status")
        data = payload.get("data")
        if status >= 400 or (code not in (None, 200)) or not isinstance(data, dict):
            message = _string(payload.get("message")) or _string(payload.get("readableMessage"))
            raise ZhihuReaderError(
                message or f"Reader failed for {target_url!r} (HTTP {status})",
                url=url,
                code=code,
                status=status or http_status,
                payload=payload,
            )
        return payload

    def _get_json(
        self, path: str, params: Optional[Mapping[str, str]] = None
    ) -> Dict[str, Any]:
        url = self.base_url + path
        if params:
            url += "?" + urlencode(params, safe=",")

        body, status = self._request(url, self._zhihu_headers())
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

    def _zhihu_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.base_url + "/",
            "User-Agent": self.user_agent,
            "X-Requested-With": "fetch",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    def _request(self, url: str, headers: Dict[str, str]) -> Tuple[bytes, int]:
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
                return body, status
            except URLError as exc:
                raise ZhihuConnectionError(
                    f"Failed to connect: {exc.reason}", url=url
                ) from exc
            return body, status

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


def _article_from_initial_data(
    entity: Dict[str, Any], article_id: str, article_url: str
) -> ArticleInfo:
    created = _timestamp(entity.get("created"))
    updated = _timestamp(entity.get("updated"))
    if created:
        time_text = _format_china_time(created)
        time_kind = "发布于"
    elif updated:
        time_text = _format_china_time(updated)
        time_kind = "编辑于"
    else:
        time_text, time_kind = None, None

    response_id = _string(entity.get("id")) or article_id
    return ArticleInfo(
        id=response_id,
        title=_string(entity.get("title")),
        author=_parse_camel_user_ref(entity.get("author")),
        column=_parse_camel_column(entity.get("column")),
        created=created,
        updated=updated,
        time_text=time_text,
        time_kind=time_kind,
        source=SOURCE_READER,
        raw={
            "article_url": article_url,
            "id": response_id,
            "title": _string(entity.get("title")),
            "created": created,
            "updated": updated,
            "author": entity.get("author"),
            "column": entity.get("column"),
        },
    )


def _parse_camel_user_ref(value: Any) -> UserRef:
    if not isinstance(value, dict):
        return UserRef()
    return UserRef(
        id=_string(value.get("id")),
        url_token=_string(value.get("urlToken")),
        name=_string(value.get("name")),
    )


def _parse_camel_column(value: Any) -> Optional[ColumnInfo]:
    if not isinstance(value, dict):
        return None
    token = _string(value.get("urlToken")) or _string(value.get("id"))
    title = _string(value.get("title"))
    author = _parse_camel_user_ref(value.get("author"))
    if not any((token, title, author.id, author.url_token, author.name)):
        return None
    return ColumnInfo(
        id=token,
        url_token=token,
        title=title,
        author=author if author.display_name or author.id else None,
        created=_timestamp(value.get("created")),
    )


def _format_china_time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=_CHINA_TZ).strftime("%Y-%m-%d %H:%M")


def _parse_article_markdown(markdown: str, fallback_title: Optional[str]) -> Dict[str, Any]:
    title = fallback_title
    if not title:
        match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
        title = _string(match.group(1)) if match else None

    section = markdown.split("\n# ", 1)[-1]
    author_match = _AUTHOR_LINK_RE.search(section)
    author = UserRef()
    if author_match:
        author = UserRef(name=_string(author_match.group(1)), url_token=author_match.group(2))

    column = None
    column_match = _COLUMN_LINK_RE.search(markdown)
    if column_match:
        token = column_match.group(2)
        column = ColumnInfo(id=token, url_token=token, title=_string(column_match.group(1)))

    return {"title": title, "author": author, "column": column}


def _parse_column_markdown(
    markdown: str, fallback_title: Optional[str], token: str
) -> Optional[ColumnInfo]:
    if not markdown:
        return None
    title = fallback_title
    if not title:
        match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
        title = _string(match.group(1)) if match else None

    section = markdown.split("专栏作者", 1)[-1]
    author_match = _AUTHOR_LINK_RE.search(section)
    author = UserRef()
    if author_match:
        author = UserRef(name=_string(author_match.group(1)), url_token=author_match.group(2))

    return ColumnInfo(
        id=token,
        url_token=token,
        title=title,
        author=author if author.display_name else None,
    )


def _parse_time_text(text: Optional[str]) -> Tuple[str, Optional[str]]:
    value = _string(text)
    if not value:
        return "", None
    match = _TIME_RE.search(value)
    if match:
        return value, match.group(1)
    if _DOTTED_DATE_RE.search(value):
        return value, "更新于"
    return value, None


def _timestamps_from_time_text(
    text: str, kind: Optional[str]
) -> Tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None

    match = _TIME_RE.search(text)
    if match:
        raw = match.group(2)
        parts = raw.split()
        date_parts = [int(part) for part in parts[0].split("-")]
        hour, minute = (int(part) for part in parts[1].split(":")) if len(parts) > 1 else (0, 0)
    else:
        dotted = _DOTTED_DATE_RE.search(text)
        if not dotted:
            return None, None
        date_parts = [int(part) for part in dotted.groups()]
        hour, minute = 0, 0

    try:
        local_dt = datetime(*date_parts, hour, minute, tzinfo=_CHINA_TZ)
    except ValueError:
        return None, None
    timestamp = int(local_dt.timestamp())

    if kind == "发布于":
        return timestamp, None
    if kind in ("编辑于", "更新于"):
        return None, timestamp
    return timestamp, None


def _parse_json(body: bytes, url: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ZhihuResponseError(f"Invalid JSON returned by {url!r}") from exc


def _api_error_from_payload(payload: Any, status: int, url: str) -> ZhihuAPIError:
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

    return error_class(message, status=status, code=code, url=url, payload=payload)


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
