fsociety client - Open Beta
================================

Run ./fsociety directly from this directory, or run ./install.sh to install it
for the current Linux user under ~/.local. Root access is not required.

The application is portable and stores each Nostr identity's encrypted vault,
SQLite state, settings, and downloaded attachments in the data subfolder beside
the fsociety executable. Keep the entire folder together when moving it. No
central fsociety server is required.

Verify the executable with: sha256sum -c SHA256SUMS.txt

Back up your Nostr recovery secret. fsociety cannot recover a lost secret or
vault password.
