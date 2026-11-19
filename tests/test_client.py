import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError

from zhihu_api import (
    ZhihuClient,
    ZhihuNotFoundError,
    extract_article_id,
    extract_member_identifier,
)

USER_ID = "0970f947b898ecc0ec035f9126dd4e08"
URL_TOKEN = "excited-vczh"
ARTICLE_ID = "140036646"

MEMBER_PAYLOAD = {
    "id": USER_ID,
    "url_token": URL_TOKEN,
    "name": "测试用户",
}

ARTICLE_PAYLOAD = {
    "id": ARTICLE_ID,
    "title": "文章标题",
    "created": 1579000000,
    "updated": 1579000100,
    "author": {
        "id": "author-id",
        "url_token": "author-token",
        "name": "文章作者",
    },
    "column": {
        "id": "column-id",
        "url_token": "column-token",
        "title": "专栏标题",
        "created": 1500000000,
        "author": {
            "id": "column-author-id",
            "url_token": "column-author-token",
            "name": "专栏作者",
        },
    },
}

READER_ARTICLE_MARKDOWN = """\
我这两年收藏的目标检测好文分享

首发于[遥感目标检测](//www.zhihu.com/column/c_1222921270964506624)

# 我这两年收藏的目标检测好文分享

[![Image](https://picx.zhimg.com/avatar_l.jpg)](javascript:void(0))

[跑者小越](//www.zhihu.com/people/pao-zhe-xiao-yue)

OpenMMLab

710 人赞同了该文章
"""

READER_COLUMN_MARKDOWN = """\
遥感目标检测

#### 专栏作者

[![Image](https://picx.zhimg.com/avatar_l.jpg)](javascript:void(0))

[跑者小越](//www.zhihu.com/people/pao-zhe-xiao-yue)

OpenMMLab
"""


READER_INITIAL_DATA = {
    "initialState": {
        "entities": {
            "articles": {
                ARTICLE_ID: {
                    "id": ARTICLE_ID,
                    "title": "我这两年收藏的目标检测好文分享",
                    "created": 1589356214,
                    "updated": 1592187916,
                    "author": {
                        "id": "author-id",
                        "urlToken": "pao-zhe-xiao-yue",
                        "name": "跑者小越",
                    },
                    "column": {
                        "id": "c_1222921270964506624",
                        "urlToken": "c_1222921270964506624",
                        "title": "遥感目标检测",
                        "created": 1584347151,
                        "author": {
                            "id": "column-author-id",
                            "urlToken": "pao-zhe-xiao-yue",
                            "name": "跑者小越",
                        },
                    },
                }
            }
        }
    }
}


def reader_envelope(content, title=None):
    data = {"content": content}
    if title:
        data["title"] = title
    return {"code": 200, "status": 20000, "data": data}


def reader_text_envelope(text):
    return {"code": 200, "status": 20000, "data": {"text": text}}


class FakeResponse:
    def __init__(self, payload, status=200):
        self.body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request.full_url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        payload, status = item
        return FakeResponse(payload, status)


class ZhihuClientTests(unittest.TestCase):
    def make_client(self, responses, source="direct"):
        opener = FakeOpener(responses)
        client = ZhihuClient(
            source=source, opener=opener, retries=0, reader_min_interval=0.0
        )
        return client, opener

    def test_get_user_id_from_url_token_and_profile_url(self):
        client, opener = self.make_client([(MEMBER_PAYLOAD, 200)] * 2)

        self.assertEqual(client.get_user_id(URL_TOKEN), USER_ID)
        self.assertEqual(
            client.get_user_id(f"https://www.zhihu.com/people/{URL_TOKEN}"),
            USER_ID,
        )
        for url in opener.requests:
            self.assertIn("/api/v4/members/" + URL_TOKEN, url)
            self.assertIn("include=id,url_token,name", url)

    def test_get_url_token_from_user_id(self):
        client, opener = self.make_client([(MEMBER_PAYLOAD, 200)])

        self.assertEqual(client.get_url_token(USER_ID), URL_TOKEN)
        self.assertIn("/api/v4/members/" + USER_ID, opener.requests[0])

    def test_reader_can_resolve_user(self):
        envelope = reader_envelope(json.dumps(MEMBER_PAYLOAD, ensure_ascii=False))
        client, opener = self.make_client([(envelope, 200)], source="reader")

        self.assertEqual(client.get_user_id(URL_TOKEN), USER_ID)
        self.assertIn("r.jina.ai/http://www.zhihu.com/api/v4/members/", opener.requests[0])

    def test_reader_requests_are_throttled(self):
        self.assertEqual(ZhihuClient().reader_min_interval, 3.0)
        envelope = reader_envelope(json.dumps(MEMBER_PAYLOAD, ensure_ascii=False))
        opener = FakeOpener([(envelope, 200)] * 2)
        client = ZhihuClient(
            source="reader",
            opener=opener,
            retries=0,
            reader_min_interval=3.0,
        )

        with patch("zhihu_api.client.time.monotonic", side_effect=[0.0, 1.0]):
            with patch("zhihu_api.client.time.sleep") as mock_sleep:
                client.get_user_id(URL_TOKEN)
                client.get_user_id(URL_TOKEN)

        mock_sleep.assert_called_once_with(2.0)

    def test_get_article_from_id_and_url(self):
        client, opener = self.make_client([(ARTICLE_PAYLOAD, 200)] * 2)

        info = client.get_article(ARTICLE_ID)
        self.assertEqual(info.title, "文章标题")
        self.assertEqual(info.author_name, "文章作者")
        self.assertEqual(info.column_title, "专栏标题")
        self.assertEqual(info.column_author.display_name, "专栏作者")
        self.assertEqual(
            info.published_at, datetime.fromtimestamp(1579000000, tz=timezone.utc)
        )

        from_url = client.get_article(f"https://zhuanlan.zhihu.com/p/{ARTICLE_ID}")
        self.assertEqual(from_url.id, ARTICLE_ID)
        self.assertIn("include=created,updated,title,author,url,column", opener.requests[0])

    def test_reader_parses_initial_data_with_exact_times_and_ids(self):
        responses = [(reader_text_envelope(json.dumps(READER_INITIAL_DATA)), 200)]
        client, opener = self.make_client(responses, source="reader")

        info = client.get_article(ARTICLE_ID)
        self.assertEqual(info.title, "我这两年收藏的目标检测好文分享")
        self.assertEqual(info.author_name, "跑者小越")
        self.assertEqual(info.author.id, "author-id")
        self.assertEqual(info.author.url_token, "pao-zhe-xiao-yue")
        self.assertEqual(info.column_title, "遥感目标检测")
        self.assertEqual(info.column.id, "c_1222921270964506624")
        self.assertEqual(info.column_author.id, "column-author-id")
        self.assertEqual(info.created, 1589356214)
        self.assertEqual(info.updated, 1592187916)
        self.assertEqual(info.time_kind, "发布于")
        self.assertEqual(
            info.published_at, datetime.fromtimestamp(1589356214, tz=timezone.utc)
        )
        self.assertEqual(
            info.updated_at, datetime.fromtimestamp(1592187916, tz=timezone.utc)
        )
        self.assertEqual(info.column.created, 1584347151)
        self.assertEqual(len(opener.requests), 1)

    def test_reader_falls_back_to_markdown_when_initial_data_missing(self):
        responses = [
            ({"code": 422, "message": "No content for selector"}, 200),
            (reader_envelope(READER_ARTICLE_MARKDOWN, "我这两年收藏的目标检测好文分享"), 200),
            (reader_envelope("编辑于 2020-06-15 02:25"), 200),
            (reader_envelope(READER_COLUMN_MARKDOWN, "遥感目标检测"), 200),
        ]
        client, opener = self.make_client(responses, source="reader")

        info = client.get_article(ARTICLE_ID)
        self.assertEqual(info.title, "我这两年收藏的目标检测好文分享")
        self.assertEqual(info.author_name, "跑者小越")
        self.assertEqual(info.column_title, "遥感目标检测")
        self.assertEqual(info.time_kind, "编辑于")
        self.assertEqual(
            info.updated_at,
            datetime(2020, 6, 14, 18, 25, tzinfo=timezone.utc),
        )
        self.assertIsNone(info.published_at)
        self.assertEqual(len(opener.requests), 4)

    def test_reader_parses_published_time_from_initial_data(self):
        article_id = "2012576370706884113"
        published_ts = int(datetime(2026, 3, 6, 1, 59, tzinfo=timezone.utc).timestamp())
        state = {
            "initialState": {
                "entities": {
                    "articles": {
                        article_id: {
                            "id": article_id,
                            "title": "新文章",
                            "created": published_ts,
                            "author": {"urlToken": "author-token", "name": "作者"},
                        }
                    }
                }
            }
        }
        client, _ = self.make_client(
            [(reader_text_envelope(json.dumps(state)), 200)], source="reader"
        )

        info = client.get_article(article_id)
        self.assertIsNone(info.column_title)
        self.assertEqual(info.time_kind, "发布于")
        self.assertEqual(info.published_at, datetime.fromtimestamp(published_ts, tz=timezone.utc))

    def test_article_without_column_falls_back_to_article_author(self):
        payload = dict(ARTICLE_PAYLOAD)
        payload.pop("column")
        client, _ = self.make_client([(payload, 200)])

        info = client.get_article(ARTICLE_ID)
        self.assertIsNone(info.column_title)
        self.assertEqual(info.column_author.display_name, "文章作者")

    def test_api_error_payload_is_mapped_to_exception(self):
        error = HTTPError(
            "https://www.zhihu.com/api/v4/articles/1",
            404,
            "Not Found",
            {},
            io.BytesIO(json.dumps({"error": {"code": 404, "message": "不存在"}}).encode()),
        )
        client, _ = self.make_client([error])

        with self.assertRaises(ZhihuNotFoundError) as context:
            client.get_article("1")
        self.assertEqual(context.exception.status, 404)
        self.assertEqual(context.exception.message, "不存在")

    def test_invalid_identifiers(self):
        with self.assertRaises(ValueError):
            extract_member_identifier("!!!")
        with self.assertRaises(ValueError):
            extract_article_id("not-a-number")
        with self.assertRaises(ValueError):
            extract_article_id("https://www.zhihu.com/people/someone")


if __name__ == "__main__":
    unittest.main()
