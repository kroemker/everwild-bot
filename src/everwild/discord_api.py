"""A small Discord REST client: only what the bot needs (design §16, §17).

No gateway connection: the bot runs once a day, reads, posts and edits.
``FakeDiscord`` has the same methods and keeps everything in memory, for
tests and for trying the turn logic without a server.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Protocol

logger = logging.getLogger("everwild.discord")

API = "https://discord.com/api/v10"
CHECK = "✅"
# allowed_mentions: only notify the users we mention explicitly
MENTION_USERS = {"parse": ["users"]}
NO_MENTIONS = {"parse": []}


class Discord(Protocol):
    def messages_after(self, channel_id: str, after: str | None) -> list[dict]: ...

    def send(self, channel_id: str, content: str = "", embeds: list[dict] | None = None,
             mentions: bool = False) -> dict: ...

    def edit(self, channel_id: str, message_id: str, content: str | None = None,
             embeds: list[dict] | None = None) -> dict: ...

    def react(self, channel_id: str, message_id: str, emoji: str = CHECK) -> None: ...

    def pin(self, channel_id: str, message_id: str) -> None: ...

    def start_thread(self, channel_id: str, message_id: str, name: str) -> dict: ...

    def modify_channel(self, channel_id: str, **fields) -> dict: ...

    def me(self) -> dict: ...


def snowflake_key(message: dict) -> int:
    return int(message["id"])


class DiscordREST:
    def __init__(self, token: str, client=None, max_retries: int = 5):
        import httpx

        self.client = client or httpx.Client(
            base_url=API, timeout=30,
            headers={"Authorization": f"Bot {token}", "User-Agent": "everwild-bot (github.com/kroemker/everwild-bot, 1.0)"},
        )
        self.max_retries = max_retries
        self._me: dict | None = None

    def _request(self, method: str, path: str, **kwargs) -> dict | list | None:
        for attempt in range(self.max_retries):
            response = self.client.request(method, path, **kwargs)
            if response.status_code == 429:
                wait = float(response.json().get("retry_after", 1.0))
                logger.info("Rate limit, warte %.1f s", wait)
                time.sleep(wait + 0.1)
                continue
            if response.status_code >= 500 and attempt < self.max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            # stay below the per-route limits without bookkeeping
            if response.headers.get("x-ratelimit-remaining") == "0":
                time.sleep(float(response.headers.get("x-ratelimit-reset-after", "1")))
            return response.json() if response.content else None
        raise RuntimeError(f"Discord: {method} {path} nach {self.max_retries} Versuchen fehlgeschlagen")

    def me(self) -> dict:
        if self._me is None:
            self._me = self._request("GET", "/users/@me")  # type: ignore[assignment]
        return self._me  # type: ignore[return-value]

    def messages_after(self, channel_id: str, after: str | None) -> list[dict]:
        """All messages after ``after``, oldest first. Without ``after``: the last 100."""
        messages: list[dict] = []
        cursor = after
        while True:
            params = {"limit": 100}
            if cursor:
                params["after"] = cursor
            page = self._request("GET", f"/channels/{channel_id}/messages", params=params) or []
            messages += page  # type: ignore[arg-type]
            if len(page) < 100 or not cursor:  # type: ignore[arg-type]
                break
            cursor = max(page, key=snowflake_key)["id"]  # type: ignore[arg-type]
        return sorted({m["id"]: m for m in messages}.values(), key=snowflake_key)

    def send(self, channel_id: str, content: str = "", embeds: list[dict] | None = None,
             mentions: bool = False) -> dict:
        body = {"content": content, "embeds": embeds or [], "allowed_mentions": MENTION_USERS if mentions else NO_MENTIONS}
        return self._request("POST", f"/channels/{channel_id}/messages", json=body)  # type: ignore[return-value]

    def edit(self, channel_id: str, message_id: str, content: str | None = None,
             embeds: list[dict] | None = None) -> dict:
        body: dict = {"allowed_mentions": NO_MENTIONS}
        if content is not None:
            body["content"] = content
        if embeds is not None:
            body["embeds"] = embeds
        return self._request("PATCH", f"/channels/{channel_id}/messages/{message_id}", json=body)  # type: ignore[return-value]

    def react(self, channel_id: str, message_id: str, emoji: str = CHECK) -> None:
        encoded = urllib.parse.quote(emoji)
        self._request("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me")

    def pin(self, channel_id: str, message_id: str) -> None:
        self._request("PUT", f"/channels/{channel_id}/pins/{message_id}")

    def start_thread(self, channel_id: str, message_id: str, name: str) -> dict:
        body = {"name": name, "auto_archive_duration": 10080}
        return self._request("POST", f"/channels/{channel_id}/messages/{message_id}/threads", json=body)  # type: ignore[return-value]

    def modify_channel(self, channel_id: str, **fields) -> dict:
        return self._request("PATCH", f"/channels/{channel_id}", json=fields)  # type: ignore[return-value]


class FakeDiscord:
    """In-memory Discord with the same methods, for tests and dry runs."""

    def __init__(self, bot_id: str = "999"):
        self.bot_id = bot_id
        self.channels: dict[str, list[dict]] = {}
        self.channel_info: dict[str, dict] = {}
        self.reactions: list[tuple[str, str, str]] = []
        self.pins: list[str] = []
        self.calls: list[str] = []
        self._next = 1_000_000

    def _id(self) -> str:
        self._next += 1
        return str(self._next)

    def me(self) -> dict:
        return {"id": self.bot_id, "username": "Everwild", "bot": True}

    def user_message(self, channel_id: str, user_id: str, name: str, content: str) -> dict:
        message = {"id": self._id(), "channel_id": channel_id, "content": content,
                   "author": {"id": user_id, "username": name.lower(), "global_name": name}}
        self.channels.setdefault(channel_id, []).append(message)
        return message

    def messages_after(self, channel_id: str, after: str | None) -> list[dict]:
        self.calls.append(f"read {channel_id}")
        messages = self.channels.get(channel_id, [])
        if after:
            messages = [m for m in messages if int(m["id"]) > int(after)]
        return sorted(messages, key=snowflake_key)

    def send(self, channel_id: str, content: str = "", embeds: list[dict] | None = None,
             mentions: bool = False) -> dict:
        if len(content) > 2000:
            raise ValueError(f"Nachricht zu lang: {len(content)} Zeichen")
        for embed in embeds or []:
            check_embed(embed)
        message = {"id": self._id(), "channel_id": channel_id, "content": content, "embeds": embeds or [],
                   "author": {"id": self.bot_id, "username": "everwild", "bot": True}, "mentions": mentions}
        self.channels.setdefault(channel_id, []).append(message)
        self.calls.append(f"send {channel_id}")
        return message

    def edit(self, channel_id: str, message_id: str, content: str | None = None,
             embeds: list[dict] | None = None) -> dict:
        for embed in embeds or []:
            check_embed(embed)
        message = next(m for m in self.channels[channel_id] if m["id"] == message_id)
        if content is not None:
            message["content"] = content
        if embeds is not None:
            message["embeds"] = embeds
        self.calls.append(f"edit {channel_id}/{message_id}")
        return message

    def react(self, channel_id: str, message_id: str, emoji: str = CHECK) -> None:
        self.reactions.append((channel_id, message_id, emoji))

    def pin(self, channel_id: str, message_id: str) -> None:
        self.pins.append(message_id)

    def start_thread(self, channel_id: str, message_id: str, name: str) -> dict:
        thread_id = self._id()
        self.channels[thread_id] = []
        self.channel_info[thread_id] = {"id": thread_id, "name": name, "parent_id": channel_id}
        return self.channel_info[thread_id]

    def modify_channel(self, channel_id: str, **fields) -> dict:
        self.channel_info.setdefault(channel_id, {"id": channel_id}).update(fields)
        self.calls.append(f"modify {channel_id}")
        return self.channel_info[channel_id]


EMBED_LIMITS = {"title": 256, "description": 4096, "field_name": 256, "field_value": 1024, "footer": 2048,
                "author": 256, "fields": 25, "total": 6000}


def check_embed(embed: dict) -> None:
    """Raises if an embed breaks one of Discord's limits."""
    total = 0
    for key, limit in (("title", "title"), ("description", "description")):
        text = embed.get(key, "")
        if len(text) > EMBED_LIMITS[limit]:
            raise ValueError(f"Embed-{key} zu lang: {len(text)}")
        total += len(text)
    footer = embed.get("footer", {}).get("text", "")
    author = embed.get("author", {}).get("name", "")
    if len(footer) > EMBED_LIMITS["footer"] or len(author) > EMBED_LIMITS["author"]:
        raise ValueError("Embed-Fußzeile oder -Autor zu lang")
    total += len(footer) + len(author)
    fields = embed.get("fields", [])
    if len(fields) > EMBED_LIMITS["fields"]:
        raise ValueError("Zu viele Embed-Felder")
    for field in fields:
        if not field["name"] or len(field["name"]) > EMBED_LIMITS["field_name"]:
            raise ValueError(f"Ungültiger Feldname: {field['name']!r}")
        if not field["value"] or len(field["value"]) > EMBED_LIMITS["field_value"]:
            raise ValueError(f"Ungültiger Feldwert in {field['name']!r}: {len(field['value'])} Zeichen")
        total += len(field["name"]) + len(field["value"])
    if total > EMBED_LIMITS["total"]:
        raise ValueError(f"Embed insgesamt zu lang: {total}")
