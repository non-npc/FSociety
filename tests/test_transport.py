from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from nostr_sdk import Keys, RelayUrl
from PyQt6.QtGui import QImage

from fsociety_client.transport import (
    create_direct_gift_wrap,
    create_auth_event,
    create_group_rumor,
    decrypt_attachment,
    encrypt_attachment,
    NostrTransport,
    unwrap_encrypted_blob,
    unwrap_direct_gift,
    wrap_encrypted_blob,
)


class NostrTransportCryptoTests(unittest.TestCase):
    def test_nip42_auth_event_is_signed_without_async_callback(self) -> None:
        keys = Keys.generate()
        relay = RelayUrl.parse("wss://inbox.test")
        event = create_auth_event(keys, relay, "relay-challenge")
        self.assertTrue(event.verify())
        self.assertEqual(event.kind().as_u16(), 22242)
        tags = [tag.to_vec() for tag in event.tags()]
        self.assertIn(["relay", str(relay)], tags)
        self.assertIn(["challenge", "relay-challenge"], tags)

    def test_incoming_gift_wrap_is_emitted_by_live_inbox_processor(self) -> None:
        sender = Keys.generate()
        receiver = Keys.generate()
        identity = SimpleNamespace(keys=receiver)
        transport = NostrTransport(identity, [], "https://primary.test", "", False)
        received: list[dict[str, object]] = []
        transport.direct_message.connect(received.append)
        event = create_direct_gift_wrap(sender, receiver.public_key(), "live hello")
        asyncio.run(transport._process_direct_event(event))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["sender"], sender.public_key().to_hex())
        self.assertEqual(received[0]["content"], "live hello")

    def test_sender_recovery_wrap_is_emitted_as_a_self_copy(self) -> None:
        sender = Keys.generate()
        recipient = Keys.generate()
        identity = SimpleNamespace(keys=sender)
        transport = NostrTransport(identity, [], "https://primary.test", "", False)
        recovered: list[dict[str, object]] = []
        transport.direct_message.connect(recovered.append)
        event = create_direct_gift_wrap(
            sender,
            recipient.public_key(),
            "my recovered message",
            wrap_for=sender.public_key(),
        )

        asyncio.run(transport._process_direct_event(event))

        self.assertEqual(len(recovered), 1)
        self.assertTrue(recovered[0]["self_copy"])
        self.assertEqual(recovered[0]["sender"], sender.public_key().to_hex())
        self.assertIn(recipient.public_key().to_hex(), recovered[0]["recipients"])

    def test_direct_send_publishes_recipient_and_sender_recovery_wraps(self) -> None:
        sender = Keys.generate()
        recipient = Keys.generate()
        identity = SimpleNamespace(keys=sender)
        transport = NostrTransport(
            identity,
            ["wss://inbox.test"],
            "https://primary.test",
            "",
            False,
            inbox_relay_urls=["wss://inbox.test"],
        )
        transport._recipient_inbox_relays = AsyncMock(return_value=["wss://inbox.test"])
        transport._publish_event = AsyncMock(return_value="wss://inbox.test")
        asyncio.run(
            transport._send_dm(
                SimpleNamespace(), 7, recipient.public_key().to_hex(), "private hello"
            )
        )
        self.assertEqual(transport._publish_event.await_count, 2)
        recipient_wrap = transport._publish_event.await_args_list[0].args[1]
        sender_wrap = transport._publish_event.await_args_list[1].args[1]
        self.assertEqual(
            [tag.to_vec()[1] for tag in recipient_wrap.tags() if tag.to_vec()[0] == "p"],
            [recipient.public_key().to_hex()],
        )
        self.assertEqual(
            [tag.to_vec()[1] for tag in sender_wrap.tags() if tag.to_vec()[0] == "p"],
            [sender.public_key().to_hex()],
        )
        recovered = unwrap_direct_gift(sender, sender_wrap)
        self.assertEqual(recovered["content"], "private hello")
        self.assertIn(recipient.public_key().to_hex(), recovered["recipients"])

    def test_encrypted_blob_png_carrier_is_valid_and_round_trips(self) -> None:
        encrypted_blob = b"ciphertext" * 100
        carrier = wrap_encrypted_blob(encrypted_blob)
        self.assertFalse(QImage.fromData(carrier, "PNG").isNull())
        self.assertEqual(unwrap_encrypted_blob(carrier), encrypted_blob)
        corrupted = bytearray(carrier)
        marker = carrier.index(b"fsOc") + 4
        corrupted[marker] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC"):
            unwrap_encrypted_blob(bytes(corrupted))

    def test_private_image_upload_uses_png_carrier_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory, "photo.png")
            image = QImage(20, 10, QImage.Format.Format_ARGB32)
            image.fill(0xFF4DEBF3)
            self.assertTrue(image.save(str(path), "PNG"))
            identity = SimpleNamespace(keys=Keys.generate())
            transport = NostrTransport(identity, [], "https://primary.test", "", False)
            upload = AsyncMock(
                return_value=(["https://primary.test/blob.png"], "aa" * 32)
            )
            with patch.object(transport, "_upload_blob", upload):
                content = asyncio.run(transport._prepare_attachment(path))
            self.assertEqual(upload.await_args.args[1], "image/png")
            envelope = json.loads(content.removeprefix("fsociety-attachment:"))
            self.assertEqual(envelope["container"], "fsociety-encrypted-png-v1")
            self.assertEqual(envelope["type"], "image/png")
            self.assertEqual(envelope["dim"], "20x10")

    def test_rar_upload_preserves_archive_type_inside_png_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory, "files.rar")
            path.write_bytes(b"private archive")
            identity = SimpleNamespace(keys=Keys.generate())
            transport = NostrTransport(identity, [], "https://primary.test", "", False)
            upload = AsyncMock(
                return_value=(["https://primary.test/blob.png"], "aa" * 32)
            )
            with patch.object(transport, "_upload_blob", upload):
                content = asyncio.run(transport._prepare_attachment(path))
            self.assertEqual(upload.await_args.args[1], "image/png")
            envelope = json.loads(content.removeprefix("fsociety-attachment:"))
            self.assertEqual(envelope["type"], "application/vnd.rar")


    def test_blossom_upload_falls_back_and_reports_success(self) -> None:
        calls: list[str] = []
        request_headers: list[dict[str, str]] = []

        class FakeHttpClient:
            def __init__(self, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args) -> None:
                pass

            async def put(self, url: str, **kwargs):
                calls.append(url)
                request_headers.append(kwargs["headers"])
                request = httpx.Request("PUT", url)
                if "primary.test" in url:
                    return httpx.Response(415, text="unsupported type", request=request)
                if calls.count("https://fallback.test/upload") == 1:
                    return httpx.Response(
                        400, text="Invalid base64 for auth event", request=request
                    )
                return httpx.Response(
                    200,
                    json={"url": "https://fallback.test/blob"},
                    request=request,
                )

        identity = SimpleNamespace(keys=Keys.generate())
        transport = NostrTransport(
            identity,
            [],
            "https://primary.test",
            "",
            False,
            blossom_fallback_url="https://fallback.test",
        )
        with patch("fsociety_client.transport.httpx.AsyncClient", FakeHttpClient):
            urls, digest = asyncio.run(
                transport._upload_blob(b"encrypted bytes", "application/octet-stream", "test")
            )
        self.assertEqual(urls, ["https://fallback.test/blob"])
        self.assertEqual(digest, hashlib.sha256(b"encrypted bytes").hexdigest())
        self.assertEqual(
            calls,
            [
                "https://primary.test/upload",
                "https://fallback.test/upload",
                "https://fallback.test/upload",
            ],
        )
        for index, headers in enumerate(request_headers):
            self.assertEqual(headers["X-SHA-256"], digest)
            encoded = headers["Authorization"].removeprefix("Nostr ")
            if index < 2:
                self.assertNotIn("=", encoded)
                encoded += "=" * (-len(encoded) % 4)
                event = json.loads(base64.urlsafe_b64decode(encoded))
            else:
                event = json.loads(base64.b64decode(encoded, validate=True))
            self.assertIn(["t", "upload"], event["tags"])
            self.assertIn(["x", digest], event["tags"])
            expected_domain = "primary.test" if index == 0 else "fallback.test"
            self.assertIn(["server", expected_domain], event["tags"])

    def test_nip17_gift_wrap_round_trip(self) -> None:
        sender = Keys.generate()
        recipient = Keys.generate()
        event = create_direct_gift_wrap(sender, recipient.public_key(), "encrypted hello")
        self.assertEqual(event.kind().as_u16(), 1059)
        self.assertTrue(event.verify())
        payload = unwrap_direct_gift(recipient, event)
        self.assertEqual(payload["sender"], sender.public_key().to_hex())
        self.assertEqual(payload["content"], "encrypted hello")

    def test_wrong_recipient_cannot_unwrap_message(self) -> None:
        sender = Keys.generate()
        recipient = Keys.generate()
        stranger = Keys.generate()
        event = create_direct_gift_wrap(sender, recipient.public_key(), "private")
        with self.assertRaises(Exception):
            unwrap_direct_gift(stranger, event)

    def test_private_group_rumor_round_trip(self) -> None:
        sender = Keys.generate()
        first = Keys.generate()
        second = Keys.generate()
        rumor = create_group_rumor(
            sender,
            [first.public_key(), second.public_key(), sender.public_key()],
            "group:abc",
            "Night Ops",
            "group secret",
            "alice",
        )
        from nostr_sdk import nip59_make_gift_wrap

        event = nip59_make_gift_wrap(sender, first.public_key(), rumor)
        payload = unwrap_direct_gift(first, event)
        self.assertEqual(payload["group_id"], "group:abc")
        self.assertEqual(payload["subject"], "Night Ops")
        self.assertEqual(payload["sender_name"], "alice")
        self.assertEqual(len(payload["recipients"]), 3)

    def test_attachment_encryption_round_trip_and_authentication(self) -> None:
        key, blob = encrypt_attachment(b"private file bytes", "evidence.bin")
        self.assertNotIn(b"private file bytes", blob)
        self.assertEqual(
            decrypt_attachment(blob, key, "evidence.bin"), b"private file bytes"
        )
        with self.assertRaises(Exception):
            decrypt_attachment(blob, key, "renamed.bin")


if __name__ == "__main__":
    unittest.main()
