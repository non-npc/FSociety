# fsociety User Guide

This guide covers the fsociety desktop client, **Open Beta v0.3.2**, on
Windows and Linux. fsociety is a decentralized messenger built on Nostr. It
uses NIP-17 encrypted messages for direct chats and private communities,
Blossom for encrypted attachments, and local SQLite databases for portable
account data and message history.

## Contents

1. [Install and start](#install-and-start)
2. [Create, import, or unlock an identity](#create-import-or-unlock-an-identity)
3. [Understand the main window](#understand-the-main-window)
4. [Manage your profile](#manage-your-profile)
5. [Use contacts and private messages](#use-contacts-and-private-messages)
6. [Create and use private communities](#create-and-use-private-communities)
7. [Send files, images, and videos](#send-files-images-and-videos)
8. [Use the Network panel](#use-the-network-panel)
9. [Configure settings](#configure-settings)
10. [Block users, remove contacts, and hide messages](#block-users-remove-contacts-and-hide-messages)
11. [Back up or reset the portable client](#back-up-or-reset-the-portable-client)
12. [Security and privacy](#security-and-privacy)
13. [Troubleshooting](#troubleshooting)

## Install and start

### Packaged release

Extract the complete release archive to a writable folder. Keep the executable,
assets, and data folder together. Start `fsociety.exe` on Windows or the
fsociety executable supplied in the Linux release.

The packaged application contains its Python runtime. Python does not need to
be installed separately.

### Run from source

Running from source requires Python 3.12 or newer and the packages listed in
`requirements.txt`. Python is available from the
[official Python download page](https://www.python.org/downloads/).

On Windows, open a terminal in the `client` folder and run:

```powershell
python -m pip install -r requirements.txt
.\run.bat
```

On Linux, install the requirements using the distribution's Python and then
run:

```sh
python3 -m pip install -r requirements.txt
sh run.sh
```

The launch screen is followed by identity access and network initialization.
The network dialog reports each configured relay's real connection state. An
unavailable relay does not prevent startup when another configured relay works.

## Create, import, or unlock an identity

A Nostr identity consists of a private recovery key and a public identity key:

- `nsec` is the private recovery secret. Never share it.
- `npub` is the public identity. Share this with people who should contact you.

### Create an identity

1. Choose the option to create a new identity.
2. Enter a public username.
3. Optionally choose a profile image.
4. Create and confirm a local vault password.
5. Copy the displayed `nsec` and store it securely offline.
6. Copy the `npub` to share your public identity.
7. Confirm that the recovery secret has been saved.

Profile images are normalized to 128 by 128 pixels. Smaller images are enlarged
and larger images are center-cropped as needed.

The local vault stores an encrypted NIP-49 representation of the secret. The
vault password is local and cannot be reset by fsociety. Losing both the vault
password and the backed-up `nsec` means losing access to the identity.

### Import an existing identity

Use the import option and enter the existing `nsec` or supported hexadecimal
secret. Choose a local username and vault password for this installation.

After import, fsociety can recover messages that are still available from the
configured relays and decryptable by that identity. Relay retention varies, so
network recovery is not a replacement for backing up the portable `data`
folder.

### Unlock a stored identity

Select the stored identity and enter its vault password. Each identity uses its
own local database, settings, contacts, groups, blocked-user list, attachments,
and message history.

## Understand the main window

Click the cyan fsociety logo to expand or collapse the navigation rail.

- **Messages** lists all direct and group conversations stored for the current
  identity. A conversation may appear here even when its participant is not an
  explicitly saved contact.
- **Contacts** lists saved people. Use it to add, remove, block, unblock, or
  open a contact profile.
- **Communities** contains private encrypted groups and group controls.
- **Network** displays live relay and NIP-17 inbox health.
- **Settings** configures endpoints, upload limits, message font size, and the
  optional moderation authority.
- **Profile** opens your public profile editor.

The `+` button starts a direct encrypted chat by public key. The `G` button
creates a private encrypted community. Search filters the list for the current
section. Unread counters clear when the conversation is opened and marked read.

When a conversation contains a large history, fsociety initially renders only
the newest 100 messages. Scrolling to the top loads 50 older messages at a time.
No more than 250 message widgets are kept in memory; the complete history stays
in SQLite and is not deleted. When the visible window moves into older history,
use **Return to Latest** to restore the newest messages. New arrivals while you
are reading older messages appear behind a **New Messages** button instead of
forcing the chat to jump or rebuilding embedded media. Conversation search
queries the complete SQLite history and displays at most the newest 250 matches.

## Manage your profile

Open **Profile** from the navigation rail or choose **View / Edit My Public
Profile** in Settings.

You can:

- change your public username;
- add, replace, or remove the profile image;
- copy your complete public `npub`;
- save the updated profile to the Nostr network.

Other users' profiles can be opened from Contacts or from a conversation's
actions menu. You may assign a local nickname without changing that person's
public Nostr profile.

Profile changes are signed with the current identity and published to connected
relays. Other clients may display cached profile information until they next
synchronize it.

## Use contacts and private messages

### Start a direct chat

1. Copy the recipient's `npub` exactly.
2. Click `+` or open **Contacts** and choose **Add Contact by npub**.
3. Paste the `npub` and confirm.
4. Select the conversation.
5. Type a message and press **Enter** or click the send arrow.

Use **Shift+Enter** when a newline is needed instead of sending. The emote
button inserts an emote at the current cursor position.

Messages progress through local, sending, and accepted states. Accepted means
at least one relay acknowledged the event; it does not prove that the recipient
has opened or read it. Failed or offline sends remain in the local outbox and
are retried after reconnection.

Links beginning with `http://` or `https://`, and common bare domains such as
`example.com`, are clickable and open in the system browser.

### Messages versus Contacts

Receiving or starting a conversation does not automatically make the other
identity a saved contact. This is intentional:

- use **Messages** for all known conversations;
- use **Contacts** for the people you explicitly saved;
- open a participant's profile and choose **Add Contact** when a Messages entry
  should also appear in Contacts.

Removing a contact does not delete the existing conversation or its local
message history.

## Create and use private communities

Groups are private NIP-17 communities. A group message is encrypted and
individually delivered to the current members. The creator is added
automatically as the first member.

### Create a group

1. Open **Communities**.
2. Choose **Create Encrypted Group** or click `G`.
3. Enter a group name.
4. Optionally enter one member `npub` per line. Leave the list empty when you
   want to invite members later.
5. Send the first message so the encrypted group reaches its members.

### Invite a member

The recipient must already have a Nostr identity. If they do not, ask them to
install fsociety, create or import an identity, back up their private `nsec`, and
send you only their public `npub`. You can then create the membership invite.

Any current group member can create an invite; this is not limited to the
original creator. The signed invite records both the member who issued it and
the original creator, so creator-only actions retain the same authority for the
new participant. fsociety groups currently use member-managed invitations and
do not provide a creator setting that disables invitations by other members.

1. Select the group in Communities.
2. Choose **Create Invite**.
3. Enter the intended recipient's `npub`.
4. Send the copied invite code privately to that exact person.

An invite is signed, targeted to one `npub`, and valid for **24 hours**. It
cannot be used by another identity. Create a separate invite for every person;
forwarding one person's code to several people does not admit the others. A
person who leaves can reuse an unexpired invite targeted to them; otherwise,
create a new invite.

### Join with an invite

1. Unlock the identity whose `npub` received the invite.
2. Open **Communities**.
3. Choose **Join With Invite**.
4. Paste the complete invite code and confirm.

Joining publishes an encrypted group system message. Leaving does the same when
other members exist and the client is connected.

### Group settings and departure

Open the conversation actions menu and choose **Group settings** to control
whether images and videos are displayed in that group. These are local display
preferences and do not alter what other members receive.

Choose **Leave or delete group** from the actions menu or **Leave / Delete
Group** in Communities:

- a regular member leaves and removes the local group history;
- the creator sends a closure notice and deletes the group locally;
- previously published Nostr events cannot be erased from relays.

## Send files, images, and videos

Click the attachment button to select a file. An image can also be pasted from
the clipboard directly into the message composer.

Before upload, attachments are encrypted locally with AES-256-GCM. The encrypted
blob is uploaded to a configured Blossom server, and the encrypted message
carries the information needed by recipients to download, verify, and decrypt
it. Recipients verify the SHA-256 hash before using the file.

- supported images are embedded in the conversation;
- animated GIF and animated PNG content plays when supported by Qt;
- supported short videos are embedded with playback controls;
- ZIP and RAR archives, along with other files, appear as verified attachments
  with a **Save File As** control and are never opened automatically;
- videos default to a 30 MB maximum;
- the general attachment limit defaults to 100 MB.

Upload time depends on file size, connection speed, and the selected Blossom
server. A queued item is retried when possible. If every configured Blossom
server rejects a media type or is unavailable, change servers in Settings or
try a supported file format.

Attachments stored on Blossom are not guaranteed permanent. Preserve important
files separately.

## Use the Network panel

Open **Network** to view live network health rather than a simulated meter. The
panel summarizes configured relays, current connections, NIP-17 inbox state,
relay acknowledgements, failures, and recent transport activity.

Connection counts distinguish configured endpoints from successful
connections. For example, one unavailable relay and two connected relays means
`2/3`, not `3/3`. Use the panel when messages remain queued or profiles do not
update.

The public Nostr feed is intentionally not ingested. Network health comes from
relay connectivity, authenticated NIP-17 inbox operation, and actual publish
acknowledgements.

## Configure settings

Settings are stored separately for the unlocked identity.

- **Primary Nostr relay** and **Fallback Nostr relay** carry general Nostr
  events and profiles.
- **NIP-17 DM inbox relay** receives authenticated private-message events.
- **Primary Blossom server** and **Fallback Blossom server** store encrypted
  attachment blobs.
- **Attachment limit** controls the largest permitted upload.
- **Short video limit** controls embedded-video uploads and cannot exceed the
  client's supported maximum.
- **Message font size** changes message content and sender names without
  resizing the application controls.
- **Idle screen** enables or disables the animated Neon Sunset Drive display.
  It is enabled by default and appears after five minutes without keyboard or
  mouse input. The first new input closes it and returns to the application;
  relay connections and message synchronization continue in the background.
- **Moderation admin key** optionally trusts signed fsociety moderation lists.

Relay addresses must use `wss://`. Blossom addresses must use `http://` or
`https://`. Custom endpoints can be typed into the editable controls.

Restart or reconnect after major endpoint changes if the old connection remains
active.

### Find or operate a Nostr relay

- Use the [Nostr.Watch relay directory](https://nostr.watch/relays/find) to
  discover public relays and review their reported availability.
- Read the official
  [NIP-11 Relay Information Document](https://github.com/nostr-protocol/nips/blob/master/11.md)
  to understand a relay's advertised capabilities, limits, authentication or
  payment requirements, operator contact, and terms.
- To run a relay yourself, consult an open-source implementation such as
  [nostr-rs-relay](https://github.com/scsibug/nostr-rs-relay) or
  [strfry](https://github.com/hoytech/strfry) and follow that project's current
  deployment and security instructions.

Relay retention and access policies are operator-specific. Use multiple
independent relays where practical and retain local backups. Self-hosting means
operating an internet-facing service with secure TLS/WebSocket access, updates,
monitoring, storage capacity, and backups; adding its `wss://` address in
fsociety only configures the client to use it.

## Block users, remove contacts, and hide messages

### Block or unblock a user

In Contacts, select a person and choose **Block / Unblock Selected User**. The
same control is available from that person's profile.

Blocking is local to the current identity. It:

- hides the blocked key's existing messages;
- discards future direct messages, group messages, attachments, and supported
  group-control events from that key;
- keeps the blocked identity visible in Contacts with a `[BLOCKED]` label so it
  can be unblocked later;
- does not remove the user or their events from the Nostr network.

Adding the same blocked `npub` again explicitly unblocks it.

### Remove a contact

Select the person in Contacts and choose **Remove Selected Contact**, or remove
them from their profile. This removes the saved-contact relationship but leaves
the local conversation available in Messages.

### Hide a message

Right-click a message and choose **Hide message locally**. The client records a
local tombstone so relay synchronization does not display that event again for
this identity. If the item was still in the outbox, its pending retry is
cancelled.

Hiding cannot erase an event already accepted by a relay, delivered to another
person, or stored as a Blossom blob.

### Delete a direct conversation locally

Open the direct chat's **More actions** menu and choose **Delete conversation
locally**. Confirming the action removes the chat from Messages and Contacts,
hides all of its current local messages, clears its unread count, and cancels
queued retries from that conversation. It does not erase events already stored
by Nostr relays or received by another person.

The chat reappears with only new visible history if a genuinely new message
arrives after deletion. Explicitly adding the same `npub` again also reopens the
conversation; previously hidden messages remain hidden.

## Back up or reset the portable client

All persistent client state is inside the `data` folder beside `main.py` during
source runs or beside the packaged executable. It contains the identity vault,
per-identity databases, settings, cached profiles, and downloaded attachments.

### Back up or move the client

1. Close fsociety completely.
2. Copy the entire client or release folder, including `data`.
3. Store the copy securely.

Moving the complete folder to another location preserves its portable data.

### Start fresh

1. Back up every required `nsec` and any wanted attachments.
2. Close fsociety completely.
3. Rename or delete the client's `data` folder.
4. Start fsociety; it creates a new empty data folder.

Deleting local data does not delete events already published to Nostr or blobs
already uploaded to Blossom. Importing an old `nsec` may recover only content
that the configured relays still retain.

## Security and privacy

- Never share an `nsec`, vault password, or decrypted identity database.
- Share only the `npub` when another person needs your public identity.
- Keep offline backups of recovery secrets and the portable `data` folder.
- Messages and group payloads use NIP-17 encrypted delivery. Relay operators can
  observe network activity and encrypted wrappers but should not receive the
  plaintext message from fsociety.
- Attachments are encrypted before Blossom upload. Blossom operators store the
  encrypted blob, but availability and deletion policies remain server-specific.
- Accepted delivery means a relay stored the event, not that the recipient read
  it.
- A new identity has new keys and cannot inherit or decrypt the old identity's
  conversations. Share the new `npub` with every person who should stay in
  contact.
- Local block lists, hidden-message records, nicknames, and display preferences
  do not modify the global Nostr network.
- fsociety moderation filters affect official fsociety clients only.

## Troubleshooting

### A relay is unavailable at startup

Continue when at least one suitable relay is connected, then open Network for
details. Check the URL in Settings or select another relay. Relay outages and
rate limits are external to the client.

### A message remains queued or sending

Open Network and verify that the NIP-17 inbox and at least one publishing relay
are connected. Keep the client running so the outbox can retry. Accepted status
appears after a relay acknowledgement.

### The recipient does not see a direct message

Confirm both users exchanged the correct `npub`, neither user blocked the other,
and their NIP-17 inbox relays are reachable. A contact name or local nickname is
not an address; delivery uses the public key.

### An attachment fails

Check the size limits, file type, and Blossom server status. Configure a working
fallback server. A Blossom server may reject unsupported media, require payment,
or apply its own retention policy.

### A conversation is visible but the person is absent from Contacts

Messages contains conversations whether or not the other identity was saved.
Open that person's profile and choose **Add Contact**.

### Old messages are missing after importing an identity

The old portable database may contain history no longer retained by the relays.
Restore the backed-up `data` folder while fsociety is closed. A recovery key can
decrypt available events but cannot force relays to retain or return deleted or
expired data.

### The application was closed during synchronization

Wait for the process to exit before starting it again. fsociety ignores late
network callbacks after shutdown, but allowing a clean exit avoids competing
processes accessing the same portable database.
