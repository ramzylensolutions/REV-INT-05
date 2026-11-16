import asyncio
import logging
import signal

from app.config import Settings
from app.db_conn import create_pool
from scripts.sender import send_next
from scripts.slack_client import SlackClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sender")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

stop = asyncio.Event()


def request_stop(*_):
    log.info("Stop signal received: finishing the current alert, then exiting")
    stop.set()


async def sleep_or_stop(seconds: float) -> None:
    """Sleep, but wake up immediately if a stop is requested."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def run() -> None:
    if Settings.slack_webhook_url is None:
        raise SystemExit("SLACK_WEBHOOK_URL is not set. The sender cannot start.")

    slack = SlackClient(Settings.slack_webhook_url.get_secret_value())
    pool = await create_pool()
    log.info("Sender started")

    try:
        while not stop.is_set():
            try:
                result = await send_next(pool, slack)
            except Exception as exc:
                log.error("Sender error: %s", type(exc).__name__)
                await sleep_or_stop(5)
                continue

            if result is None:
                await sleep_or_stop(2)                      # nothing waiting
            elif result["outcome"] == "rate_limited":
                log.warning("Slack rate limit, waiting %s s", result["retry_after"])
            else:
                if "count" in result:
                    log.info("Summary of %s alerts %s", result["count"], result["outcome"])
                else:
                    log.info("Alert %s", result["outcome"])
                await sleep_or_stop(1)
    finally:
        await pool.close()
        log.info("Sender stopped cleanly")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    asyncio.run(run())