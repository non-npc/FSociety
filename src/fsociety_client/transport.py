from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import queue
import struct
import time
import zlib
from datetime import timedelta
from urllib.parse import urlparse
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from nostr_sdk import (
    Client,
    ClientMessage,
    ClientNotification,
    EventBuilder,
    Filter,
    Kind,
    PublicKey,
    RelayStatus,
    RelayMessageEnum,
    RelayUrl,
    ReqTarget,
    SendEventTarget,
    Tag,
    Timestamp,
    UnwrappedGift,
    nip59_make_gift_wrap,
)
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImageReader

from .attachment_types import guess_attachment_mime
from .identity import UnlockedIdentity
from .reactions import encode_reaction


def create_direct_rumor(
    keys,
    recipient: PublicKey,
    content: str,
    created_at: int | None = None,
):
    builder = EventBuilder(Kind(14), content).tags([Tag.public_key(recipient)])
    if created_at is not None:
        builder = builder.custom_created_at(Timestamp.from_secs(created_at))
    return builder.finalize_unsigned(keys.public_key()).ensure_id()


def create_direct_gift_wrap(
    keys, recipient: PublicKey, content: str, wrap_for: PublicKey | None = None
):
    rumor = create_direct_rumor(keys, recipient, content)
    return nip59_make_gift_wrap(keys, wrap_for or recipient, rumor)


def create_auth_event(keys, relay_url: RelayUrl, challenge: str):
    return (
        EventBuilder(Kind(22242), "")
        .tags(
            [
                Tag.custom("relay", [str(relay_url)]),
                Tag.custom("challenge", [challenge]),
            ]
        )
        .finalize(keys)
    )


def unwrap_direct_gift(keys, event) -> dict[str, object]:
    gift = UnwrappedGift.from_gift_wrap(keys, event)
    rumor = gift.rumor()
    if rumor.kind().as_u16() != 14:
        raise ValueError("Gift wrap does not contain a NIP-17 private message.")
    tags = [tag.to_vec() for tag in rumor.tags()]
    recipients = [tag[1] for tag in tags if len(tag) >= 2 and tag[0] == "p"]
    subject = next((tag[1] for tag in tags if len(tag) >= 2 and tag[0] == "subject"), "")
    group_id = next((tag[1] for tag in tags if len(tag) >= 2 and tag[0] == "h"), "")
    sender_name = next((tag[1] for tag in tags if len(tag) >= 2 and tag[0] == "name"), "")
    return {
        "sender": gift.sender().to_hex(),
        "content": rumor.content(),
        "event_id": event.id().to_hex(),
        "message_ref": rumor.ensure_id().id().to_hex(),
        "sent_at": rumor.created_at().as_secs(),
        "recipients": recipients,
        "subject": subject,
        "group_id": group_id,
        "sender_name": sender_name,
    }


def create_group_rumor(
    keys,
    members: list[PublicKey],
    group_id: str,
    name: str,
    content: str,
    sender_name: str = "",
    created_at: int | None = None,
):
    tags = [Tag.public_key(member) for member in members]
    tags.extend([Tag.custom("h", [group_id]), Tag.custom("subject", [name])])
    if sender_name.strip():
        tags.append(Tag.custom("name", [sender_name.strip()]))
    builder = EventBuilder(Kind(14), content).tags(tags)
    if created_at is not None:
        builder = builder.custom_created_at(Timestamp.from_secs(created_at))
    return builder.finalize_unsigned(keys.public_key()).ensure_id()


def encrypt_attachment(data: bytes, name: str) -> tuple[bytes, bytes]:
    key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    return key, nonce + AESGCM(key).encrypt(nonce, data, name.encode("utf-8"))


def decrypt_attachment(blob: bytes, key: bytes, name: str) -> bytes:
    if len(blob) < 13:
        raise ValueError("Encrypted attachment is truncated.")
    return AESGCM(key).decrypt(blob[:12], blob[12:], name.encode("utf-8"))


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FSOCIETY_PNG_CHUNK = b"fsOc"


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def wrap_encrypted_blob(encrypted_blob: bytes) -> bytes:
    """Put ciphertext in a valid private, safe-to-copy PNG ancillary chunk."""
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    transparent_pixel = zlib.compress(b"\x00\x00\x00\x00\x00")
    return b"".join(
        (
            PNG_SIGNATURE,
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", transparent_pixel),
            _png_chunk(FSOCIETY_PNG_CHUNK, encrypted_blob),
            _png_chunk(b"IEND", b""),
        )
    )


def unwrap_encrypted_blob(carrier: bytes) -> bytes:
    if not carrier.startswith(PNG_SIGNATURE):
        raise ValueError("Encrypted attachment carrier is not a PNG.")
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(carrier):
        length = struct.unpack(">I", carrier[offset : offset + 4])[0]
        chunk_end = offset + 12 + length
        if chunk_end > len(carrier):
            raise ValueError("Encrypted attachment PNG chunk is truncated.")
        chunk_type = carrier[offset + 4 : offset + 8]
        data = carrier[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", carrier[offset + 8 + length : chunk_end])[0]
        if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != expected_crc:
            raise ValueError("Encrypted attachment PNG chunk failed CRC verification.")
        if chunk_type == FSOCIETY_PNG_CHUNK:
            return data
        if chunk_type == b"IEND":
            break
        offset = chunk_end
    raise ValueError("PNG does not contain an fsociety encrypted attachment.")


class NostrTransport(QThread):
    connected = pyqtSignal(int)
    connection_failed = pyqtSignal(str)
    relay_status = pyqtSignal(str, str)
    direct_message = pyqtSignal(object)
    message_published = pyqtSignal(int, str, str, str)
    message_failed = pyqtSignal(int, str)
    profile_published = pyqtSignal(str, str, str)
    profile_failed = pyqtSignal(str)
    attachment_status = pyqtSignal(int, str)
    public_profile = pyqtSignal(object)
    reaction_published = pyqtSignal(int, str, str)
    reaction_failed = pyqtSignal(int, str)

    def __init__(
        self,
        identity: UnlockedIdentity,
        relay_urls: list[str],
        blossom_url: str,
        profile_fingerprint: str,
        publish_profile: bool,
        existing_picture_url: str = "",
        attachments_directory: str = "",
        max_upload_bytes: int = 100 * 1024 * 1024,
        blossom_fallback_url: str = "",
        inbox_relay_urls: list[str] | None = None,
        max_video_bytes: int = 30 * 1024 * 1024,
    ) -> None:
        super().__init__()
        self.identity = identity
        self.relay_urls = relay_urls
        self.blossom_urls = list(
            dict.fromkeys(
                value.rstrip("/")
                for value in (blossom_url, blossom_fallback_url)
                if value.strip()
            )
        )
        self.blossom_url = self.blossom_urls[0] if self.blossom_urls else ""
        self.inbox_relay_urls = list(
            dict.fromkeys(
                value.strip()
                for value in (inbox_relay_urls or relay_urls)
                if value.strip()
            )
        )[:3]
        self._inbox_cache: dict[str, tuple[float, list[str]]] = {}
        self.profile_fingerprint = profile_fingerprint
        self.publish_profile_on_connect = publish_profile
        self.existing_picture_url = existing_picture_url
        self.attachments_directory = Path(attachments_directory)
        self.max_upload_bytes = max_upload_bytes
        self.max_video_bytes = max_video_bytes
        self.commands: queue.Queue[tuple[str, tuple[object, ...]]] = queue.Queue()
        self._since = max(0, int(time.time()) - 7 * 86400)

    def send_direct_message(self, message_id: int, recipient: str, content: str) -> None:
        self.commands.put(("send_dm", (message_id, recipient, content)))

    def send_attachment(
        self, message_id: int, recipient: str, path: str, caption: str = ""
    ) -> None:
        self.commands.put(("send_attachment", (message_id, recipient, path, caption)))

    def send_group(
        self, message_id: int, group_id: str, name: str, members: list[str], content: str
    ) -> None:
        self.commands.put(("send_group", (message_id, group_id, name, members, content)))

    def send_group_attachment(
        self,
        message_id: int,
        group_id: str,
        name: str,
        members: list[str],
        path: str,
        caption: str = "",
    ) -> None:
        self.commands.put(
            ("send_group_attachment", (message_id, group_id, name, members, path, caption))
        )

    def send_reaction(
        self,
        outbox_id: int,
        target_ref: str,
        emoji: str,
        active: bool,
        created_at: int,
        recipients: list[str],
        group_id: str = "",
        group_name: str = "",
    ) -> None:
        self.commands.put(
            (
                "send_reaction",
                (
                    outbox_id,
                    target_ref,
                    emoji,
                    active,
                    created_at,
                    recipients,
                    group_id,
                    group_name,
                ),
            )
        )

    def refresh_profiles(self, pubkeys: list[str]) -> None:
        self.commands.put(("profiles", (pubkeys,)))

    def run(self) -> None:
        try:
            asyncio.run(self._run_transport())
        except Exception as error:
            self.connection_failed.emit(str(error))

    async def _run_transport(self) -> None:
        if not self.relay_urls:
            raise ValueError("Configure at least one Nostr relay.")
        backoff = 2
        while not self.isInterruptionRequested():
            client = Client()
            try:
                for value in self.relay_urls:
                    self.relay_status.emit(value, "CONNECTING")
                    await client.add_relay(RelayUrl.parse(value))
                await client.connect()
                await asyncio.sleep(2.0)
                relays = await client.relays()
                for value in self.relay_urls:
                    relay = await client.relay(RelayUrl.parse(value))
                    status = relay.status() if relay is not None else None
                    self.relay_status.emit(
                        value,
                        "CONNECTED" if status == RelayStatus.CONNECTED else "UNAVAILABLE",
                    )
                connected_count = sum(
                    relay.status() == RelayStatus.CONNECTED for relay in relays.values()
                )
                if connected_count == 0:
                    raise RuntimeError("No configured Nostr relay connected.")
                notifications = client.notifications()
                self.relay_status.emit("NIP-17 PRIVATE INBOX", "CONFIGURING")
                try:
                    await self._publish_inbox_preferences(client)
                except Exception as error:
                    self.connection_failed.emit(
                        f"NIP-17 inbox preference publish warning: {error}"
                    )
                dm_filter = (
                    Filter()
                    .kind(Kind(1059))
                    .pubkey(self.identity.keys.public_key())
                    .since(Timestamp.from_secs(max(0, int(time.time()) - 7 * 86400)))
                    .limit(1000)
                )
                await client.subscribe(
                    ReqTarget.auto([dm_filter]), id="fsociety-nip17-inbox"
                )
                self.relay_status.emit("NIP-17 PRIVATE INBOX", "CONNECTED")
                await asyncio.sleep(0.2)
                for _ in range(100):
                    try:
                        notification = await asyncio.wait_for(
                            notifications.next(), timeout=0.02
                        )
                    except TimeoutError:
                        break
                    if notification is None:
                        break
                    await self._handle_notification(client, notification, dm_filter)
                self.connected.emit(connected_count)
                backoff = 2
                if self.publish_profile_on_connect:
                    try:
                        await self._publish_profile(client)
                        self.publish_profile_on_connect = False
                    except Exception as error:
                        self.profile_failed.emit(str(error))
                next_health = time.monotonic() + 15.0
                while not self.isInterruptionRequested():
                    while True:
                        try:
                            command, values = self.commands.get_nowait()
                        except queue.Empty:
                            break
                        if command == "send_dm":
                            await self._send_dm(
                                client, int(values[0]), str(values[1]), str(values[2])
                            )
                        elif command == "send_attachment":
                            await self._send_attachment(
                                client,
                                int(values[0]),
                                str(values[1]),
                                str(values[2]),
                                str(values[3]),
                            )
                        elif command == "send_group":
                            await self._send_group(
                                client,
                                int(values[0]),
                                str(values[1]),
                                str(values[2]),
                                list(values[3]),
                                str(values[4]),
                            )
                        elif command == "send_reaction":
                            await self._send_reaction(
                                client,
                                int(values[0]),
                                str(values[1]),
                                str(values[2]),
                                bool(values[3]),
                                int(values[4]),
                                list(values[5]),
                                str(values[6]),
                                str(values[7]),
                            )
                        elif command == "send_group_attachment":
                            await self._send_group_attachment(
                                client,
                                int(values[0]),
                                str(values[1]),
                                str(values[2]),
                                list(values[3]),
                                str(values[4]),
                                str(values[5]),
                            )
                        elif command == "profiles":
                            await self._fetch_profiles(client, list(values[0]))
                    for _ in range(50):
                        try:
                            notification = await asyncio.wait_for(
                                notifications.next(), timeout=0.002
                            )
                        except TimeoutError:
                            break
                        if notification is None:
                            break
                        await self._handle_notification(client, notification, dm_filter)
                    if time.monotonic() >= next_health:
                        relays = await client.relays()
                        connected_count = sum(
                            relay.status() == RelayStatus.CONNECTED for relay in relays.values()
                        )
                        for value in self.relay_urls:
                            relay = await client.relay(RelayUrl.parse(value))
                            status = relay.status() if relay is not None else None
                            self.relay_status.emit(
                                value,
                                "CONNECTED"
                                if status == RelayStatus.CONNECTED
                                else "UNAVAILABLE",
                            )
                        if connected_count == 0:
                            raise RuntimeError("All Nostr relays disconnected.")
                        self.connected.emit(connected_count)
                        next_health = time.monotonic() + 15.0
                    await asyncio.sleep(0.15)
            except Exception as error:
                for value in self.relay_urls:
                    self.relay_status.emit(value, "UNAVAILABLE")
                self.connection_failed.emit(f"{error} Retrying in {backoff}s.")
            finally:
                await client.shutdown()
            if self.isInterruptionRequested():
                break
            for _ in range(backoff * 10):
                if self.isInterruptionRequested():
                    break
                await asyncio.sleep(0.1)
            backoff = min(backoff * 2, 60)

    async def _send_dm(
        self, client: Client, message_id: int, recipient_value: str, content: str
    ) -> None:
        try:
            recipient = PublicKey.parse(recipient_value)
            rumor = create_direct_rumor(self.identity.keys, recipient, content)
            gift_wrap = nip59_make_gift_wrap(self.identity.keys, recipient, rumor)
            recipient_relays = await self._recipient_inbox_relays(client, recipient)
            successful = await self._publish_event(
                client,
                gift_wrap,
                SendEventTarget.to([RelayUrl.parse(value) for value in recipient_relays]),
            )
            self_copy = nip59_make_gift_wrap(
                self.identity.keys, self.identity.keys.public_key(), rumor
            )
            try:
                await self._publish_event(
                    client,
                    self_copy,
                    SendEventTarget.to(
                        [RelayUrl.parse(value) for value in self.inbox_relay_urls]
                    ),
                )
            except Exception:
                pass
            self.message_published.emit(
                message_id, gift_wrap.id().to_hex(), successful, rumor.id().to_hex()
            )
        except Exception as error:
            self.message_failed.emit(message_id, str(error))

    async def _send_attachment(
        self,
        client: Client,
        message_id: int,
        recipient_value: str,
        filename: str,
        caption: str = "",
    ) -> None:
        try:
            content = await self._prepare_attachment(Path(filename), message_id, caption)
            recipient = PublicKey.parse(recipient_value)
            rumor = create_direct_rumor(self.identity.keys, recipient, content)
            gift_wrap = nip59_make_gift_wrap(self.identity.keys, recipient, rumor)
            recipient_relays = await self._recipient_inbox_relays(client, recipient)
            successful = await self._publish_event(
                client,
                gift_wrap,
                SendEventTarget.to([RelayUrl.parse(value) for value in recipient_relays]),
            )
            self_copy = nip59_make_gift_wrap(
                self.identity.keys, self.identity.keys.public_key(), rumor
            )
            try:
                await self._publish_event(
                    client,
                    self_copy,
                    SendEventTarget.to(
                        [RelayUrl.parse(value) for value in self.inbox_relay_urls]
                    ),
                )
            except Exception:
                pass
            self.message_published.emit(
                message_id, gift_wrap.id().to_hex(), successful, rumor.id().to_hex()
            )
        except Exception as error:
            self.message_failed.emit(message_id, str(error))

    async def _send_group_attachment(
        self,
        client: Client,
        message_id: int,
        group_id: str,
        name: str,
        member_values: list[str],
        filename: str,
        caption: str = "",
    ) -> None:
        try:
            content = await self._prepare_attachment(Path(filename), message_id, caption)
        except Exception as error:
            self.message_failed.emit(message_id, str(error))
            return
        await self._send_group(client, message_id, group_id, name, member_values, content)

    async def _prepare_attachment(
        self, path: Path, message_id: int = 0, caption: str = ""
    ) -> str:
        size = path.stat().st_size
        if size > self.max_upload_bytes:
            raise ValueError("Attachment exceeds the configured upload limit.")
        self.attachment_status.emit(message_id, f"Encrypting {path.name}…")
        plaintext = path.read_bytes()
        key, encrypted_blob = encrypt_attachment(plaintext, path.name)
        carrier = wrap_encrypted_blob(encrypted_blob)
        mime_type = guess_attachment_mime(path.name)
        self.attachment_status.emit(
            message_id, f"Uploading encrypted {path.name} to Blossom…"
        )
        urls, digest = await self._upload_blob(
            carrier, "image/png", "encrypted attachment carrier"
        )
        original_digest = hashlib.sha256(plaintext).hexdigest()
        envelope = {
            "v": 2,
            "name": path.name,
            "size": size,
            "type": mime_type,
            "container": "fsociety-encrypted-png-v1",
            "container_type": "image/png",
            "container_size": len(carrier),
            "url": urls[0],
            "urls": urls,
            "fallback": urls[1:],
            "x": digest,
            "ox": original_digest,
            "alt": path.name,
            "caption": caption.strip(),
            "key": base64.b64encode(key).decode("ascii"),
        }
        if mime_type.startswith("image/"):
            dimensions = QImageReader(str(path)).size()
            if dimensions.isValid():
                envelope["dim"] = f"{dimensions.width()}x{dimensions.height()}"
        return "fsociety-attachment:" + json.dumps(
            envelope, ensure_ascii=False, separators=(",", ":")
        )

    async def _publish_event(self, client: Client, event, target=None) -> str:
        output = (
            await client.send_event(event, target=target)
            if target is not None
            else await client.send_event(event)
        )
        successful = [str(url) for url in output.success]
        if not successful:
            failures = "; ".join(f"{url}: {reason}" for url, reason in output.failed.items())
            raise RuntimeError(failures or "No relay accepted the signed event.")
        return ", ".join(successful)

    async def _publish_inbox_preferences(self, client: Client) -> None:
        if not self.inbox_relay_urls:
            return
        event = (
            EventBuilder(Kind(10050), "")
            .tags([Tag.custom("relay", [value]) for value in self.inbox_relay_urls])
            .finalize(self.identity.keys)
        )
        await self._publish_event(client, event)

    async def _handle_notification(
        self, client: Client, notification, inbox_filter: Filter
    ) -> None:
        if isinstance(notification, ClientNotification.NEW_EVENT):
            event = notification.event
            if event.kind().as_u16() == 1059:
                await self._process_direct_event(event)
        elif isinstance(notification, ClientNotification.MESSAGE):
            message = notification.message.as_enum()
            if isinstance(message, RelayMessageEnum.AUTH):
                await self._authenticate_relay(
                    client,
                    notification.relay_url,
                    message.challenge,
                    inbox_filter,
                )

    async def _authenticate_relay(
        self,
        client: Client,
        relay_url: RelayUrl,
        challenge: str,
        inbox_filter: Filter,
    ) -> None:
        relay = await client.relay(relay_url)
        if relay is None:
            return
        event = create_auth_event(self.identity.keys, relay_url, challenge)
        await relay.send_msg(ClientMessage.auth(event))
        await client.subscribe(
            ReqTarget.single(relay_url, [inbox_filter]),
            id=f"fsociety-nip17-auth-{int(time.time() * 1000)}",
        )

    async def _recipient_inbox_relays(
        self, client: Client, recipient: PublicKey
    ) -> list[str]:
        pubkey = recipient.to_hex()
        cached = self._inbox_cache.get(pubkey)
        if cached is not None and time.monotonic() - cached[0] < 600:
            return cached[1]
        event_filter = Filter().author(recipient).kind(Kind(10050)).limit(5)
        try:
            events = await client.fetch_events(
                ReqTarget.auto([event_filter]), timedelta(seconds=4), max_events=5
            )
        except Exception:
            events = []
        relays: list[str] = []
        if events:
            newest = max(events, key=lambda event: event.created_at().as_secs())
            for tag in newest.tags():
                values = tag.to_vec()
                if len(values) >= 2 and values[0] == "relay":
                    try:
                        relays.append(str(RelayUrl.parse(values[1])))
                    except Exception:
                        continue
        if not relays:
            relays = list(self.inbox_relay_urls or self.relay_urls)
        relays = list(dict.fromkeys(relays))[:3]
        added = False
        for value in relays:
            added = await client.add_relay(
                RelayUrl.parse(value), and_connect=True
            ) or added
        if added:
            await asyncio.sleep(1.0)
        self._inbox_cache[pubkey] = (time.monotonic(), relays)
        return relays

    async def _send_group(
        self,
        client: Client,
        message_id: int,
        group_id: str,
        name: str,
        member_values: list[str],
        content: str,
    ) -> None:
        try:
            own = self.identity.keys.public_key().to_hex()
            members = [
                PublicKey.parse(value)
                for value in dict.fromkeys(member_values)
                if PublicKey.parse(value).to_hex() != own
            ]
            if not members:
                raise ValueError("The group has no other members.")
            rumor_members = [*members, self.identity.keys.public_key()]
            rumor = create_group_rumor(
                self.identity.keys,
                rumor_members,
                group_id,
                name,
                content,
                self.identity.record.username,
            )
            first_event_id = ""
            accepted_relays: set[str] = set()
            for member in members:
                wrap = nip59_make_gift_wrap(self.identity.keys, member, rumor)
                if not first_event_id:
                    first_event_id = wrap.id().to_hex()
                inbox_relays = await self._recipient_inbox_relays(client, member)
                accepted_relays.update(
                    (
                        await self._publish_event(
                            client,
                            wrap,
                            SendEventTarget.to(
                                [RelayUrl.parse(value) for value in inbox_relays]
                            ),
                        )
                    ).split(", ")
                )
            self_wrap = nip59_make_gift_wrap(
                self.identity.keys, self.identity.keys.public_key(), rumor
            )
            try:
                await self._publish_event(
                    client,
                    self_wrap,
                    SendEventTarget.to(
                        [RelayUrl.parse(value) for value in self.inbox_relay_urls]
                    ),
                )
            except Exception:
                pass
            self.message_published.emit(
                message_id,
                first_event_id,
                ", ".join(sorted(accepted_relays)),
                rumor.id().to_hex(),
            )
        except Exception as error:
            self.message_failed.emit(message_id, str(error))

    async def _send_reaction(
        self,
        client: Client,
        outbox_id: int,
        target_ref: str,
        emoji: str,
        active: bool,
        created_at: int,
        recipient_values: list[str],
        group_id: str,
        group_name: str,
    ) -> None:
        try:
            content = encode_reaction(target_ref, emoji, active)
            own_key = self.identity.keys.public_key()
            own = own_key.to_hex()
            recipients = [
                PublicKey.parse(value)
                for value in dict.fromkeys(recipient_values)
                if PublicKey.parse(value).to_hex() != own
            ]
            if not recipients:
                raise ValueError("Reaction has no recipient.")
            if group_id:
                rumor = create_group_rumor(
                    self.identity.keys,
                    [*recipients, own_key],
                    group_id,
                    group_name or "Encrypted group",
                    content,
                    self.identity.record.username,
                    created_at,
                )
            else:
                rumor = create_direct_rumor(
                    self.identity.keys, recipients[0], content, created_at
                )
            accepted_relays: set[str] = set()
            for recipient in recipients:
                wrap = nip59_make_gift_wrap(self.identity.keys, recipient, rumor)
                inbox_relays = await self._recipient_inbox_relays(client, recipient)
                accepted_relays.update(
                    (
                        await self._publish_event(
                            client,
                            wrap,
                            SendEventTarget.to(
                                [RelayUrl.parse(value) for value in inbox_relays]
                            ),
                        )
                    ).split(", ")
                )
            self_wrap = nip59_make_gift_wrap(self.identity.keys, own_key, rumor)
            try:
                await self._publish_event(
                    client,
                    self_wrap,
                    SendEventTarget.to(
                        [RelayUrl.parse(value) for value in self.inbox_relay_urls]
                    ),
                )
            except Exception:
                pass
            self.reaction_published.emit(
                outbox_id, rumor.id().to_hex(), ", ".join(sorted(accepted_relays))
            )
        except Exception as error:
            self.reaction_failed.emit(outbox_id, str(error))

    async def _fetch_profiles(self, client: Client, pubkey_values: list[str]) -> None:
        authors: list[PublicKey] = []
        for value in dict.fromkeys(pubkey_values):
            try:
                authors.append(PublicKey.parse(value))
            except Exception:
                continue
        if not authors:
            return
        authors = authors[:200]
        event_filter = Filter().authors(authors).kind(Kind(0)).limit(len(authors) * 3)
        try:
            events = await self._fetch_event_batch(client, event_filter, len(authors) * 3)
        except Exception:
            return
        newest: dict[str, object] = {}
        for event in events:
            if not event.verify():
                continue
            pubkey = event.author().to_hex()
            existing = newest.get(pubkey)
            if existing is None or event.created_at().as_secs() > existing.created_at().as_secs():
                newest[pubkey] = event
        for event in newest.values():
            try:
                metadata = json.loads(event.content())
            except Exception:
                continue
            picture = str(metadata.get("picture", ""))
            picture_blob = b""
            if picture.startswith(("http://", "https://")):
                try:
                    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as http:
                        response = await http.get(picture)
                        response.raise_for_status()
                        if len(response.content) <= 2 * 1024 * 1024:
                            picture_blob = response.content
                except Exception:
                    pass
            self.public_profile.emit(
                {
                    "pubkey": event.author().to_hex(),
                    "name": str(metadata.get("name", "")),
                    "display_name": str(metadata.get("display_name", "")),
                    "picture": picture,
                    "about": str(metadata.get("about", "")),
                    "nip05": str(metadata.get("nip05", "")),
                    "picture_blob": picture_blob,
                    "updated_at": event.created_at().as_secs(),
                }
            )

    async def _fetch_event_batch(self, client: Client, event_filter: Filter, limit: int) -> list:
        """Fetch a bounded batch per relay and deduplicate the combined result."""
        events_by_id: dict[str, object] = {}
        failures: list[str] = []
        for relay_value in self.relay_urls:
            try:
                events = await client.fetch_events(
                    ReqTarget.single(RelayUrl.parse(relay_value), [event_filter]),
                    timedelta(seconds=5),
                    max_events=limit,
                )
            except Exception as error:
                failures.append(f"{relay_value}: {error}")
                continue
            for event in events:
                events_by_id[event.id().to_hex()] = event
        if not events_by_id and failures:
            raise RuntimeError("; ".join(failures))
        return sorted(
            events_by_id.values(),
            key=lambda event: event.created_at().as_secs(),
            reverse=True,
        )[:limit]

    async def _fetch_direct_messages(self, client: Client) -> None:
        public_key = self.identity.keys.public_key()
        event_filter = (
            Filter()
            .kind(Kind(1059))
            .pubkey(public_key)
            .since(Timestamp.from_secs(self._since))
            .limit(500)
        )
        try:
            events = await client.fetch_events(
                ReqTarget.auto([event_filter]), timedelta(seconds=4), max_events=500
            )
        except Exception as error:
            self.connection_failed.emit(f"Relay synchronization failed: {error}")
            return
        for event in events:
            await self._process_direct_event(event)

    async def _process_direct_event(self, event) -> None:
        try:
            payload = unwrap_direct_gift(self.identity.keys, event)
            # The sender publishes a gift-wrapped copy to their own NIP-17
            # inbox. Those copies are required to reconstruct the outgoing
            # half of a conversation on a fresh portable database.
            payload["self_copy"] = (
                payload["sender"] == self.identity.keys.public_key().to_hex()
            )
            if str(payload["content"]).startswith("fsociety-attachment:"):
                try:
                    attachment = await self._download_attachment(str(payload["content"]))
                    payload["content"] = attachment["content"]
                    payload["attachment_path"] = attachment["path"]
                    payload["attachment_mime"] = attachment["mime"]
                except Exception as error:
                    payload["content"] = f"📎 Encrypted attachment download failed: {error}"
            self.direct_message.emit(payload)
        except Exception:
            return

    async def _publish_profile(self, client: Client) -> None:
        picture_url = self.existing_picture_url
        if self.identity.record.avatar_png and not picture_url:
            picture_urls, _ = await self._upload_blob(
                self.identity.record.avatar_png, "image/png", "profile image"
            )
            picture_url = picture_urls[0]
        metadata: dict[str, str] = {
            "name": self.identity.record.username,
            "display_name": self.identity.record.username,
        }
        if picture_url:
            metadata["picture"] = picture_url
        event = EventBuilder(
            Kind(0), json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
        ).finalize(self.identity.keys)
        output = await client.send_event(event)
        successful = [str(url) for url in output.success]
        if not successful:
            failures = "; ".join(f"{url}: {reason}" for url, reason in output.failed.items())
            raise RuntimeError(failures or "No relay accepted the signed profile.")
        self.profile_published.emit(
            self.profile_fingerprint, picture_url, ", ".join(successful)
        )

    async def _upload_blob(
        self, blob: bytes, mime_type: str, description: str
    ) -> tuple[list[str], str]:
        servers = [
            server
            for server in self.blossom_urls
            if server.startswith(("http://", "https://"))
        ]
        if not servers:
            raise ValueError("Configure at least one valid Blossom server.")
        digest = hashlib.sha256(blob).hexdigest()
        async def upload_one(server: str) -> tuple[str, str, str]:
            expiration = int(time.time()) + 300
            server_domain = (urlparse(server).hostname or "").lower()
            authorization = (
                EventBuilder(Kind(24242), f"Authorize {description} upload")
                .tags(
                    [
                        Tag.custom("t", ["upload"]),
                        Tag.custom("expiration", [str(expiration)]),
                        Tag.custom("x", [digest]),
                        Tag.custom("server", [server_domain]),
                    ]
                )
                .finalize(self.identity.keys)
            )
            authorization_json = authorization.as_json().encode("utf-8")
            token = base64.urlsafe_b64encode(authorization_json).rstrip(b"=").decode("ascii")
            legacy_token = base64.b64encode(authorization_json).decode("ascii")

            async def put_with_token(http, auth_token: str):
                return await http.put(
                    f"{server}/upload",
                    content=blob,
                    headers={
                        "Authorization": f"Nostr {auth_token}",
                        "Content-Type": mime_type,
                        "Content-Length": str(len(blob)),
                        "X-SHA-256": digest,
                    },
                )

            try:
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
                    response = await put_with_token(http, token)
                    error_text = response.text.lower() if response.is_error else ""
                    if response.is_error and "base64" in error_text:
                        response = await put_with_token(http, legacy_token)
                if response.is_error:
                    detail = " ".join(response.text.strip().split())[:240]
                    return (
                        server,
                        "",
                        f"HTTP {response.status_code}" + (f" — {detail}" if detail else ""),
                    )
                payload = response.json()
                url = str(payload.get("url", "")).strip()
                if not url:
                    return server, "", "response did not contain a blob URL"
                descriptor_hash = str(payload.get("sha256", digest)).lower()
                if descriptor_hash != digest:
                    return server, "", "response blob hash does not match uploaded bytes"
                return server, url, ""
            except Exception as error:
                return server, "", str(error)

        results = await asyncio.gather(*(upload_one(server) for server in servers))
        urls = list(dict.fromkeys(url for _, url, error in results if url and not error))
        if urls:
            return urls, digest
        failures = [f"{server}: {error}" for server, _, error in results]
        raise RuntimeError("All Blossom uploads failed: " + "; ".join(failures))

    async def _download_attachment(self, content: str) -> dict[str, str]:
        envelope = json.loads(content.removeprefix("fsociety-attachment:"))
        expected_size = int(envelope["size"])
        expected_mime = str(envelope.get("type", "application/octet-stream")).lower()
        if expected_size < 0 or expected_size > self.max_upload_bytes:
            raise ValueError("Attachment size exceeds the configured limit.")
        if expected_mime.startswith("video/") and expected_size > self.max_video_bytes:
            raise ValueError("Video exceeds the configured short-video limit.")
        candidates = [str(envelope.get("url", ""))]
        if isinstance(envelope.get("urls"), list):
            candidates.extend(str(url) for url in envelope["urls"])
        if isinstance(envelope.get("fallback"), list):
            candidates.extend(str(url) for url in envelope["fallback"])
        candidates = list(
            dict.fromkeys(
                url for url in candidates if url.startswith(("http://", "https://"))
            )
        )
        if not candidates:
            raise ValueError("Attachment has no valid HTTP or HTTPS Blossom URL.")
        download_errors: list[str] = []
        encrypted_blob = b""
        for attachment_url in candidates:
            try:
                async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as http:
                    response = await http.get(attachment_url)
                    response.raise_for_status()
                    declared = int(response.headers.get("content-length", "0") or 0)
                    if declared > self.max_upload_bytes + 4096:
                        raise ValueError("response exceeds the configured limit")
                    candidate_blob = response.content
                if len(candidate_blob) > self.max_upload_bytes + 4096:
                    raise ValueError("download exceeds the configured limit")
                if hashlib.sha256(candidate_blob).hexdigest() != str(envelope["x"]).lower():
                    raise ValueError("SHA-256 verification failed")
                encrypted_blob = candidate_blob
                break
            except Exception as error:
                download_errors.append(f"{attachment_url}: {error}")
        if not encrypted_blob:
            raise RuntimeError("All Blossom downloads failed: " + "; ".join(download_errors))
        if envelope.get("container") == "fsociety-encrypted-png-v1":
            encrypted_blob = unwrap_encrypted_blob(encrypted_blob)
        key = base64.b64decode(str(envelope["key"]), validate=True)
        name = Path(str(envelope["name"])).name or "attachment.bin"
        plaintext = decrypt_attachment(encrypted_blob, key, name)
        if len(plaintext) != expected_size:
            raise ValueError("Decrypted attachment size does not match metadata.")
        original_digest = str(envelope.get("ox", "")).lower()
        if original_digest and hashlib.sha256(plaintext).hexdigest() != original_digest:
            raise ValueError("Original attachment SHA-256 verification failed.")
        self.attachments_directory.mkdir(parents=True, exist_ok=True)
        safe_name = f"{str(envelope['x'])[:12]}-{name}"
        destination = self.attachments_directory / safe_name
        destination.write_bytes(plaintext)
        mime_type = str(envelope.get("type", "application/octet-stream")).lower()
        caption = str(envelope.get("caption") or "").strip()
        description = f"📎 {name}\nDownloaded, decrypted, and SHA-256 verified"
        if caption:
            description = f"{caption}\n{description}"
        return {
            "content": description,
            "path": str(destination),
            "mime": mime_type,
        }
