#!/bin/bash
# Create a throwaway password store with invented passwords.
#
# Manual testing, screenshots and one-off probes should use this, never
# ~/.password-store: see src/gtkpass/safety.py.
set -euo pipefail

STORE="${1:-.dev/store}"
GNUPG="${2:-.dev/gnupg}"
KEY="gtkpass-dev@example.invalid"

if [ -f "$STORE/.gpg-id" ]; then
    echo "Development store already present at $STORE"
    exit 0
fi

mkdir -p "$STORE" "$GNUPG"
chmod 700 "$GNUPG"
export GNUPGHOME="$(cd "$GNUPG" && pwd)"

if ! gpg --list-keys "$KEY" >/dev/null 2>&1; then
    echo "Generating a throwaway key (no passphrase, never leaves .dev/)..."
    gpg --batch --pinentry-mode loopback --passphrase '' \
        --quick-generate-key "GTKPass Development <$KEY>" default default never
fi

echo "$KEY" > "$STORE/.gpg-id"

# Nothing here is a real credential.
add() {
    mkdir -p "$STORE/$(dirname "$1")"
    gpg --batch --yes --encrypt --recipient "$KEY" \
        --trust-model always --output "$STORE/$1.gpg"
}

add "email/personal" <<'ENTRY'
hunter2
username: someone@example.invalid
url: https://mail.example.invalid
notes: Fake account for development
ENTRY

add "email/work" <<'ENTRY'
correct-horse-battery
username: someone@work.example.invalid
url: https://work.example.invalid
ENTRY

add "bank/checking" <<'ENTRY'
not-a-real-password
username: dev-user
url: https://bank.example.invalid
account: 000000000
ENTRY

add "social/example" <<'ENTRY'
swordfish
login: dev-user
website: https://social.example.invalid
ENTRY

add "work/servers/staging" <<'ENTRY'
tr0ub4dor
user: root
uri: ssh://staging.example.invalid
Reachable only from the VPN.
ENTRY

add "no-metadata" <<'ENTRY'
just-a-password
ENTRY

echo "Development store ready: $STORE ($(find "$STORE" -name '*.gpg' | wc -l) entries)"
