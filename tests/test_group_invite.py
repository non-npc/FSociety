from __future__ import annotations

import unittest
import time

from nostr_sdk import Keys

from fsociety_client.group_invite import create_group_invite, parse_group_invite


class GroupInviteTests(unittest.TestCase):
    def test_signed_targeted_invite_round_trip(self) -> None:
        creator = Keys.generate()
        invitee = Keys.generate()
        code = create_group_invite(
            creator,
            "group:test",
            "Test Group",
            invitee.public_key().to_bech32(),
            [creator.public_key().to_hex()],
        )
        invite = parse_group_invite(code, invitee.public_key().to_hex())
        self.assertEqual(invite.group_id, "group:test")
        self.assertEqual(invite.name, "Test Group")
        self.assertEqual(invite.inviter, creator.public_key().to_hex())
        self.assertEqual(invite.creator, creator.public_key().to_hex())
        self.assertIn(creator.public_key().to_hex(), invite.members)
        self.assertIn(invitee.public_key().to_hex(), invite.members)
        remaining = invite.expires_at - int(time.time())
        self.assertGreaterEqual(remaining, 24 * 60 * 60 - 2)
        self.assertLessEqual(remaining, 24 * 60 * 60)

    def test_invite_for_another_identity_is_rejected(self) -> None:
        creator = Keys.generate()
        invitee = Keys.generate()
        stranger = Keys.generate()
        code = create_group_invite(
            creator, "group:test", "Test", invitee.public_key().to_hex(), []
        )
        with self.assertRaisesRegex(ValueError, "different Nostr identity"):
            parse_group_invite(code, stranger.public_key().to_hex())

    def test_member_invite_preserves_original_creator_authority(self) -> None:
        creator = Keys.generate()
        member = Keys.generate()
        invitee = Keys.generate()
        code = create_group_invite(
            member,
            "group:member-invite",
            "Member Invite",
            invitee.public_key().to_hex(),
            [creator.public_key().to_hex(), member.public_key().to_hex()],
            creator_pubkey=creator.public_key().to_hex(),
        )
        invite = parse_group_invite(code, invitee.public_key().to_hex())
        self.assertEqual(invite.inviter, member.public_key().to_hex())
        self.assertEqual(invite.creator, creator.public_key().to_hex())


if __name__ == "__main__":
    unittest.main()
