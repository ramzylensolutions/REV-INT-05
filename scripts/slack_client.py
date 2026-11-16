from dataclasses import dataclass

import httpx


@dataclass
class SendResult:
    outcome: str                    # "sent", "retry", "park", "rate_limited"
    error: str | None = None        # short and safe, never the URL
    retry_after: int | None = None  # seconds, only for rate_limited


class SlackClient:
    def __init__(self, webhook_url: str, timeout_seconds: float = 5.0, transport=None):
        self._webhook_url = webhook_url
        self._timeout = timeout_seconds
        self._transport = transport  # only used by tests

    async def send(self, payload: dict) -> SendResult:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(self._webhook_url, json=payload)
        except httpx.TimeoutException:
            return SendResult("retry", "timeout")
        except httpx.HTTPError as exc:
            return SendResult("retry", type(exc).__name__)  # class name only, never the message

        if response.status_code == 200:
            return SendResult("sent")

        if response.status_code == 429:
            return SendResult("rate_limited", "rate_limited",
                              retry_after=_parse_retry_after(response))

        if response.status_code >= 500:
            return SendResult("retry", f"http {response.status_code}")

        return SendResult("park", f"http {response.status_code}: {response.text[:100]}")


def _parse_retry_after(response: httpx.Response) -> int:
    try:
        return max(1, int(response.headers.get("Retry-After", "30")))
    except ValueError:
        return 30