import argparse
import json
import sys
from typing import Optional, Sequence

from .client import DEFAULT_BASE_URL, SOURCE_DIRECT, SOURCE_READER, ZhihuClient
from .errors import ZhihuError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zhihu-api",
        description="Query public Zhihu user and column article data.",
    )
    parser.add_argument(
        "--source",
        choices=(SOURCE_READER, SOURCE_DIRECT),
        default=SOURCE_READER,
        help="Data source (default: public reader proxy)",
    )
    parser.add_argument("--cookie", help="Optional Zhihu cookie for direct source")
    parser.add_argument(
        "--reader-api-key",
        help="Optional Jina API key (defaults to JINA_API_KEY env var)",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="Request timeout")
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL, help=argparse.SUPPRESS
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    user_id = subparsers.add_parser("user-id", help="Resolve url_token to user id")
    user_id.add_argument("identifier", help="url_token or profile URL")

    url_token = subparsers.add_parser("url-token", help="Resolve user id to url_token")
    url_token.add_argument("identifier", help="user id or member API URL")

    article = subparsers.add_parser("article", help="Get column article metadata")
    article.add_argument("identifier", help="article id or article URL")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    client = ZhihuClient(
        source=args.source,
        base_url=args.base_url,
        timeout=args.timeout,
        cookie=args.cookie,
        reader_api_key=args.reader_api_key,
    )

    try:
        if args.command == "user-id":
            print(client.get_user_id(args.identifier))
        elif args.command == "url-token":
            print(client.get_url_token(args.identifier))
        elif args.command == "article":
            info = client.get_article(args.identifier)
            print(json.dumps(info.as_dict(), ensure_ascii=False, indent=2))
        else:  # pragma: no cover - argparse enforces the choices
            raise ValueError(f"Unknown command: {args.command!r}")
    except (ZhihuError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
