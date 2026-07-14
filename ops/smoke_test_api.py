import argparse
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    body = None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{method} {url} failed with HTTP {error.code}: {error_body}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"{method} {url} failed: {error.reason}") from error

    if not response_body:
        return {}

    return json.loads(response_body)


def smoke_test_api(
    base_url: str,
    *,
    message: str,
    top_k: int = 3,
    rerank_top_k: int = 3,
    health_only: bool = False,
    ready_only: bool = False,
    api_key: str | None = None,
    timeout: float = 30,
) -> int:
    base_url = base_url.rstrip("/")

    health = request_json(
        "GET",
        f"{base_url}/health",
        timeout=timeout,
    )
    print(f"Health: {health}")
    if health.get("status") != "ok":
        print("Health check did not return status=ok.")
        return 1

    if health_only:
        return 0

    readiness = request_json(
        "GET",
        f"{base_url}/ready",
        timeout=timeout,
    )
    print(f"Readiness: {readiness}")
    if readiness.get("status") != "ready":
        print("Readiness check did not return status=ready.")
        return 1

    if ready_only:
        return 0

    chat = request_json(
        "POST",
        f"{base_url}/chat",
        payload={
            "message": message,
            "top_k": top_k,
            "rerank_top_k": rerank_top_k,
        },
        headers={"X-API-Key": api_key} if api_key else None,
        timeout=timeout,
    )
    print(f"Answer length: {len(chat.get('answer', ''))}")
    print(f"Source count: {len(chat.get('sources', []))}")

    if not chat.get("answer"):
        print("Chat response did not include an answer.")
        return 1

    if not chat.get("sources"):
        print("Chat response did not include sources.")
        return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the FastAPI RAG API."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base API URL. Defaults to http://localhost:8000.",
    )
    parser.add_argument(
        "--message",
        default="墨尔本 校招",
        help="Message to send to POST /chat.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Retriever top_k for /chat.",
    )
    parser.add_argument(
        "--rerank-top-k",
        type=int,
        default=3,
        help="Reranker top_k for /chat.",
    )
    parser.add_argument(
        "--health-only",
        action="store_true",
        help="Only check GET /health.",
    )
    parser.add_argument(
        "--ready-only",
        action="store_true",
        help="Check GET /health and GET /ready without calling /chat.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("CHAT_API_KEY"),
        help="Internal chat API key. Defaults to CHAT_API_KEY.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="HTTP timeout in seconds.",
    )
    args = parser.parse_args()

    try:
        return smoke_test_api(
            args.base_url,
            message=args.message,
            top_k=args.top_k,
            rerank_top_k=args.rerank_top_k,
            health_only=args.health_only,
            ready_only=args.ready_only,
            api_key=args.api_key,
            timeout=args.timeout,
        )
    except RuntimeError as error:
        print(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
