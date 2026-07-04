import os
from dataclasses import dataclass, field


WECHAT_API_KEY_ENV = "WECHAT_API_KEY"
DEFAULT_FAKE_ID = "MjM5OTAxNTM0MA=="
DEFAULT_BASE_URL = "https://down.mptext.top/api/public/v1"


@dataclass(frozen=True)
class WechatHarvesterConfig:
    api_key: str
    fake_id: str = DEFAULT_FAKE_ID
    base_url: str = DEFAULT_BASE_URL
    page_size: int = 20
    request_timeout_seconds: float = 10
    delay_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError(
                f"{WECHAT_API_KEY_ENV} is required to run the WeChat harvester"
            )
        if self.page_size <= 0:
            raise ValueError("page_size must be greater than zero")
        if self.request_timeout_seconds <= 0:
            raise ValueError(
                "request_timeout_seconds must be greater than zero"
            )
        if self.delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")

    @classmethod
    def from_environment(cls) -> "WechatHarvesterConfig":
        return cls(api_key=os.getenv(WECHAT_API_KEY_ENV, ""))


@dataclass
class HarvestState:
    begin: int = 0
    total_saved: int = 0
    valid_count: int = 0
    seen_links: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ArticleOutput:
    location: str
    article_count: int


@dataclass(frozen=True)
class HarvestResult:
    output_location: str
    articles_written: int
    total_saved: int
    valid_count: int
