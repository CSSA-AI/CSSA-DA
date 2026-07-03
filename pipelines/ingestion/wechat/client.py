import urllib.parse
from typing import Any, Protocol

import requests

from pipelines.ingestion.wechat.models import WechatHarvesterConfig


class WechatApiError(RuntimeError):
    """Raised when the WeChat source rejects or malforms a request."""


class ArticleSourceClient(Protocol):
    def list_articles(self, begin: int) -> list[dict[str, Any]]: ...

    def download_article(self, link: str) -> str: ...


class WechatClient:
    def __init__(
        self,
        config: WechatHarvesterConfig,
        *,
        http_client: Any = requests,
    ):
        self.config = config
        self.http_client = http_client

    def list_articles(self, begin: int) -> list[dict[str, Any]]:
        response = self.http_client.get(
            f"{self.config.base_url}/article",
            headers={"X-Auth-Key": self.config.api_key},
            params={
                "fakeid": self.config.fake_id,
                "begin": begin,
                "size": self.config.page_size,
            },
            timeout=self.config.request_timeout_seconds,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise WechatApiError("WeChat API returned an invalid response")

        base_response = payload.get("base_resp", {})
        if base_response.get("ret") != 0:
            message = base_response.get("err_msg")
            raise WechatApiError(
                f"WeChat API rejected the request: {message}"
            )

        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            raise WechatApiError(
                "WeChat API returned an invalid articles collection"
            )
        return articles

    def download_article(self, link: str) -> str:
        encoded_url = urllib.parse.quote(link, safe="")
        response = self.http_client.get(
            f"{self.config.base_url}/download"
            f"?url={encoded_url}&format=markdown",
            timeout=self.config.request_timeout_seconds,
        )

        try:
            payload = response.json()
        except (AttributeError, ValueError):
            return response.text

        if isinstance(payload, dict):
            return payload.get("data", "")
        return response.text
