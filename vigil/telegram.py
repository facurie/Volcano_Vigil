"""Telegram: post the fountaining alerts to a public channel through a bot (https://core.telegram.org/bots/api).

The bot's token is a secret, and the Bot API puts it in the URL of every request. So this module never logs a
request, it takes the token out of every error it raises, and its CLI raises the httpx logger to WARNING (httpx
logs each request's URL at INFO).

    vigil-telegram check   # the token works, and the bot may post in the channel
    vigil-telegram test    # post a message that says it is a test, not an alert
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

import httpx

from vigil.config import load_sources
from vigil.settings import Settings

API = "https://api.telegram.org"
CAPTION_MAX = 1024  # characters in a photo's caption (Bot API, sendPhoto)
TEST_MESSAGE = ("Volcano Vigil test message: the alert channel works. It is not an alert.\n\n"
                "Official status: {agency}: {url}")


class TelegramError(RuntimeError):
    """A Bot API call failed. The message never holds the token."""


class Telegram:
    def __init__(self, http: httpx.Client, token: str, chat: str, api: str = API):
        self._http, self._token, self.chat, self._api = http, token, chat, api

    def _call(self, method: str, *, data: dict[str, Any] | None = None, files: dict[str, Any] | None = None) -> Any:
        try:
            response = self._http.post(f"{self._api}/bot{self._token}/{method}", data=data, files=files, timeout=30)
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError(self._redact(f"{method}: {type(exc).__name__}: {exc}")) from None
        if not body.get("ok"):
            raise TelegramError(self._redact(f"{method}: {body.get('error_code')} {body.get('description')}"))
        return body["result"]

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "<token>")

    def send_photo(self, photo: bytes, caption: str) -> int:
        """Post a JPEG with its caption; returns the message id."""
        if len(caption) > CAPTION_MAX:
            raise ValueError(f"a caption has at most {CAPTION_MAX} characters; this one has {len(caption)}")
        result = self._call("sendPhoto", data={"chat_id": self.chat, "caption": caption},
                            files={"photo": ("alert.jpg", photo, "image/jpeg")})
        return result["message_id"]

    def send_message(self, text: str) -> int:
        return self._call("sendMessage", data={"chat_id": self.chat, "text": text})["message_id"]

    def check(self) -> dict[str, Any]:
        """Who the bot is, which chat it posts to, and whether it may post there."""
        me = self._call("getMe")
        chat = self._call("getChat", data={"chat_id": self.chat})
        member = self._call("getChatMember", data={"chat_id": self.chat, "user_id": me["id"]})
        return {"bot": f"@{me['username']}", "chat": chat.get("title") or chat.get("username") or str(chat["id"]),
                "chat_id": chat["id"], "type": chat["type"], "status": member["status"],
                "can_post": member["status"] == "creator" or bool(member.get("can_post_messages"))}


def describe(check: dict[str, Any]) -> str:
    return (f"{check['bot']} posts to {check['chat']} ({check['chat_id']}, {check['type']}): {check['status']}, "
            f"may post: {'yes' if check['can_post'] else 'no'}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Check the Telegram bot that posts the fountaining alerts, or post "
                                                 "a test message to its channel.")
    parser.add_argument("action", choices=["check", "test"])
    parser.add_argument("--volcano", default="kilauea", help="whose official agency the test message links to")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if not settings.telegram_token or not settings.telegram_chat:
        parser.error("set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (in .env locally, as Space secrets on the Space)")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # a Windows console cannot show 'ī' in the channel's name
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines would print the token
    with httpx.Client() as http:
        telegram = Telegram(http, settings.telegram_token, settings.telegram_chat, settings.telegram_api)
        try:
            if args.action == "check":
                print(describe(telegram.check()))
            else:
                volcano = load_sources(settings.sources_path).volcanoes[args.volcano]
                message_id = telegram.send_message(TEST_MESSAGE.format(agency=volcano.official_agency,
                                                                       url=volcano.official_url))
                print(f"posted the test as message {message_id} to {settings.telegram_chat}")
        except TelegramError as exc:
            raise SystemExit(f"Telegram: {exc}") from None
