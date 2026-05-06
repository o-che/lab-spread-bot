import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
from telegram import Bot
from telegram.error import TelegramError

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
SYMBOL = "LABUSDT"
INTERVAL = 60  # seconds

ASTERDEX_PREMIUM_URL = "https://fapi.asterdex.com/fapi/v1/premiumIndex"
BITGET_TICKER_URL = "https://api.bitget.com/api/v2/spot/market/tickers"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SpreadBot/1.0)",
    "Accept": "application/json",
}


async def fetch_asterdex(client: httpx.AsyncClient) -> dict:
    r = await client.get(
        ASTERDEX_PREMIUM_URL,
        params={"symbol": SYMBOL},
        headers=HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return {
        "mark_price": float(data["markPrice"]),
        "funding_rate": float(data["lastFundingRate"]),
        "next_funding_time": int(data["nextFundingTime"]),
    }


async def fetch_bitget(client: httpx.AsyncClient) -> float:
    r = await client.get(
        BITGET_TICKER_URL,
        params={"symbol": SYMBOL},
        headers=HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return float(data["data"][0]["lastPr"])


def build_message(
    futures_price: float,
    spot_price: float,
    funding_rate: float,
    next_funding_ts: int,
) -> str:
    spread = futures_price - spot_price
    spread_pct = (spread / spot_price) * 100
    funding_pct = funding_rate * 100

    next_funding_dt = datetime.fromtimestamp(next_funding_ts / 1000, tz=timezone.utc)
    mins_to_funding = max(
        0,
        int((next_funding_dt - datetime.now(tz=timezone.utc)).total_seconds() / 60),
    )

    now = datetime.now(tz=timezone.utc).strftime("%H:%M:%S UTC")
    arrow = "🔺" if spread > 0 else "🔻"

    return (
        f"<b>LAB/USDT · {now}</b>\n\n"
        f"📈 Futures (AsterDEX): <code>{futures_price:.5f}</code>\n"
        f"💰 Spot   (Bitget):    <code>{spot_price:.5f}</code>\n\n"
        f"{arrow} <b>Спред:</b> <code>{spread:+.5f}</code>  (<code>{spread_pct:+.3f}%</code>)\n"
        f"💸 <b>Funding (1h):</b> <code>{funding_pct:+.4f}%</code>  "
        f"(через {mins_to_funding} мин)"
    )


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    log.info("Bot started. Symbol=%s  ChatID=%s", SYMBOL, CHAT_ID)

    async with httpx.AsyncClient() as client:
        while True:
            try:
                aster, spot_price = await asyncio.gather(
                    fetch_asterdex(client),
                    fetch_bitget(client),
                )
                text = build_message(
                    futures_price=aster["mark_price"],
                    spot_price=spot_price,
                    funding_rate=aster["funding_rate"],
                    next_funding_ts=aster["next_funding_time"],
                )
                await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")
                log.info("Sent: spread=%.5f", aster["mark_price"] - spot_price)
            except TelegramError as e:
                log.error("Telegram error: %s", e)
            except httpx.HTTPError as e:
                log.error("HTTP error: %s", e)
            except Exception as e:
                log.exception("Unexpected error: %s", e)

            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
