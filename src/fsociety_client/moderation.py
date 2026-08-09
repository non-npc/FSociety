from __future__ import annotations

import asyncio
from datetime import timedelta

from nostr_sdk import Client, Filter, Kind, PublicKey, RelayUrl, ReqTarget
from PyQt6.QtCore import QThread, pyqtSignal


class ModerationSyncWorker(QThread):
    synced = pyqtSignal(object, object, str)
    failed = pyqtSignal(str)

    def __init__(self, admin_key: str, relay_urls: list[str]) -> None:
        super().__init__()
        self.admin_key = admin_key
        self.relay_urls = relay_urls

    def run(self) -> None:
        try:
            users, posts, event_id = asyncio.run(self._sync())
        except Exception as error:
            self.failed.emit(str(error))
            return
        self.synced.emit(users, posts, event_id)

    async def _sync(self) -> tuple[list[str], list[str], str]:
        admin = PublicKey.parse(self.admin_key)
        if not self.relay_urls:
            raise ValueError("No moderation relay is configured.")
        client = Client()
        try:
            for value in self.relay_urls:
                await client.add_relay(RelayUrl.parse(value))
            await client.connect()
            event_filter = Filter().author(admin).kind(Kind(10000)).limit(20)
            events = await client.fetch_events(
                ReqTarget.auto([event_filter]), timedelta(seconds=8), max_events=20
            )
            valid = [
                event
                for event in events
                if event.verify() and event.author().to_hex() == admin.to_hex()
            ]
            if not valid:
                raise RuntimeError("No valid fsociety moderation list was found on the relays.")
            newest = max(valid, key=lambda event: event.created_at().as_secs())
            users: list[str] = []
            posts: list[str] = []
            for tag in newest.tags():
                values = tag.to_vec()
                if len(values) < 2:
                    continue
                if values[0] == "p":
                    try:
                        users.append(PublicKey.parse(values[1]).to_hex())
                    except Exception:
                        continue
                elif values[0] == "e":
                    try:
                        from nostr_sdk import EventId

                        posts.append(EventId.parse(values[1]).to_hex())
                    except Exception:
                        continue
            return list(dict.fromkeys(users)), list(dict.fromkeys(posts)), newest.id().to_hex()
        finally:
            await client.shutdown()
