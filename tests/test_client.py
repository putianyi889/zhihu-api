import io
import json
import unittest
from datetime import datetime, timezone
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
    def make_client(self, responses):
        opener = FakeOpener(responses)
        client = ZhihuClient(opener=opener, retries=0)
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
