#!/usr/bin/env python3

from __future__ import annotations

import hashlib
from urllib.parse import quote, urlsplit

import httpx

URLS = [
    "https://en.wikisource.org/wiki/Page:Canadian_patent_29537.djvu/2",
    "http://localhost:18581/index.php/Page:Canadian_patent_29537.djvu/2",
]


def raw_url(page_url: str) -> str:
    parsed = urlsplit(page_url)

    if "/wiki/" in parsed.path:
        title = parsed.path.split("/wiki/", 1)[1]
        script = "/w/index.php"
    elif "/index.php/" in parsed.path:
        title = parsed.path.split("/index.php/", 1)[1]
        script = "/index.php"
    else:
        raise ValueError(f"Unrecognised MediaWiki URL: {page_url}")

    return (
        f"{parsed.scheme}://{parsed.netloc}{script}"
        f"?title={quote(title, safe=':/.')}&action=raw"
    )


def base36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"

    if value == 0:
        return "0"

    result: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        result.append(digits[remainder])

    return "".join(reversed(result))


def mediawiki_sha1(data: bytes) -> str:
    hex_digest = hashlib.sha1(data).hexdigest()
    return base36(int(hex_digest, 16)).rjust(31, "0")


def main() -> None:
    with httpx.Client(
        follow_redirects=True,
        timeout=30,
        headers={
            "User-Agent": "wikisource-sha1-check/1.0",
        },
    ) as client:
        for page_url in URLS:
            url = raw_url(page_url)
            response = client.get(url)
            response.raise_for_status()

            data = response.content

            print(f"Page:          {page_url}")
            print(f"Raw URL:       {response.url}")
            print(f"Bytes:         {len(data)}")
            print(f"SHA-1 hex:     {hashlib.sha1(data).hexdigest()}")
            print(f"MediaWiki SHA: {mediawiki_sha1(data)}")
            print(f"First bytes:   {data[:80]!r}")
            print(f"Last bytes:    {data[-80:]!r}")
            print()


if __name__ == "__main__":
    main()
