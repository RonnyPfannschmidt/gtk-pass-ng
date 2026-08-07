# Per-machine keys, and what decryption actually costs

A design note, not a description of shipped behaviour. GTKPass already supports
the storage side of this — a store encrypted to several recipients works today,
and the numbers below were measured against it — but it has no interface for
rotating the recipient set, which is the part that makes the model
administrable. That gap is stated at the end.

Everything measured here was measured on one machine (gpg 2.4.9, libgcrypt
1.12.2) against throwaway keys and a scratch store. Nothing here read a real
password.

## The cost this is solving

`gpg-agent` caches the **passphrase**, not the unlocked key. Every private-key
operation re-derives the key-protection key from that cached passphrase by
running S2K again. GnuPG calibrates the iteration count so that takes roughly
100ms — deliberately, as brute-force resistance — and you pay it on every single
decrypt, cache warm or not.

| key protection | per decrypt |
| --- | --- |
| none (`protection=C`) | **13 ms** |
| passphrase, `s2k-count 1024` | **16 ms** |
| passphrase, default calibrated count | **147 ms** |

Same passphrase, same warm cache, same algorithm in all three; only the
iteration count differs. So the ~135ms is the KDF and nothing else.

The cache masks re-*prompting*, not this cost:

- `default-cache-ttl` is 600s and its timer resets on each access, so continuous
  use keeps the entry alive.
- `max-cache-ttl` is 7200s and is absolute — *"a cache entry will be expired
  even if it has been accessed recently"*. Keeping a key warm by poking it does
  not work past two hours, and each poke costs a full operation anyway.

### Neither batching nor threads help

Both were measured, because both look like they should.

| approach | result |
| --- | --- |
| `gpg --decrypt-files` over 10 entries in one process | 154 ms each vs 155 ms — no gain |
| 8-way parallelism on a 22-core machine | 1.05× — `gpg-agent` serialises |
| an agent option to cache the *unprotected* key | does not exist; the only cache options are the four TTLs, `ignore-cache-for-signing` and `no-allow-external-cache` |

S2K is per-operation by design, so there is nothing to amortise. This is why the
four-worker pool in `BackendManager` buys responsiveness rather than throughput,
and why listing and searching must never decrypt: on a 200-entry store that is
30 seconds of KDF.

## The model

Give every machine its own key, and make each machine's key an **additional
recipient** on the store rather than the only one.

```
$ cat ~/.password-store/.gpg-id
laptop@example.invalid
desktop@example.invalid
master@example.invalid
```

`pass` and GTKPass both encrypt each entry to every recipient listed. The master
key stays offline — on a token, or on paper in a safe — and is what guarantees
you can still open the store when every machine is gone.

Three properties fall out of this, and they are the reason to bother:

**Speed.** A machine holds only its own secret, and that key can be one with no
S2K cost — TPM-bound or passphrase-free. Verified: a store encrypted to a
passphrase-free machine key and a passphrase-protected master decrypts in
**13-15 ms** on the machine, against 147 ms for the master. There is no risk of
picking the slow key by accident, because the slow key's secret is not on that
machine at all.

**Revocation by construction.** Retiring a machine is removing a line from
`.gpg-id`. There is no key material to hunt down across machines and no
revocation certificate to distribute.

**Scoping.** `.gpg-id` can live in a subdirectory, and both backends resolve the
nearest one walking upward. A work laptop can be a recipient on `work/` and
never able to open `bank/` at all.

### What this does not change

The master key remains the thing that can open everything, so it is worth the
offline handling. And a machine key is a full recipient: while it is enrolled,
that machine can read everything in its scope. This model limits *blast radius
and duration*, not access.

## Binding a machine key to its TPM

`gpg --edit-key <machine-key>` then `keytotpm` replaces the on-disk secret with
a form that only that machine's TPM can unwrap. The key is not moved into the
TPM — it is encrypted by it, in place. No passphrase means no S2K.

Requirements, from the GnuPG manual and from what is actually installed:

- A TPM 2.0 and `/dev/tpmrm0`, with the user in the `tss` group — *"It is
  essential to use the physical system TPM that you have rw permission on the
  TPM resource manager device"*.
- `tpm2daemon`, which ships with GnuPG (here at `/usr/libexec/tpm2daemon`) and is
  started by `gpg-agent` on demand.
- An algorithm the TPM supports. **All TPM 2.0 devices are mandated to have
  rsa2048 and nistp256; newer ones may have more.** Generate machine keys
  accordingly — a modern ed25519 default will not transfer.

Read the warnings before running it. From the manual, verbatim:

> the keyfile now becomes locked to the laptop containing the TPM […] the key
> file can never be converted back to non-TPM form and the key will die when the
> TPM does, so you should first have a backup on secure offline storage

Those warnings are fatal for a *sole* recipient and harmless for an additional
one. That asymmetry is the whole point of the model: a machine key is meant to
die with its machine, and the master is the backup the manual is telling you to
keep.

### What TPM binding protects against — and what it does not

Worth being blunt, because the acronym invites more confidence than the
implementation earns.

GnuPG's TPM support has **no PCR policy binding**: `tpm2daemon` exposes only
`--tpm2-parent`, and neither it nor `gpg --edit-key` documents an auth value or
PIN on the resulting key. So the blob unwraps whenever the TPM is reachable —
which is whenever the machine has booted and the user can read `/dev/tpmrm0`.

| threat | protected? |
| --- | --- |
| a copy of the store, or a disk image, taken off the machine | **yes** — the blob is useless without that specific TPM |
| a stolen powered-off machine with full-disk encryption | **yes**, by the disk encryption, not by the TPM |
| a stolen machine with no FDE, or taken while unlocked | **no** — the TPM is right there and will unwrap |

**Full-disk encryption is not optional in this model.** The TPM binding stops the
key blob travelling; it does nothing about someone holding the whole running
machine. Treat TPM binding as removing the S2K cost and pinning the key to
hardware, not as a second factor.

Unmeasured, and worth measuring before committing: the TPM's own operation cost.
The speed argument rests entirely on eliminating S2K, and TPMs are deliberately
low-power parts — an RSA-2048 operation on a discrete TPM can land in the same
100ms range as the KDF it replaces. Benchmark a throwaway TPM key before
converting anything, and remember `keytotpm` is one-way.

## Retiring a device

Removing a machine from `.gpg-id` and re-encrypting protects **future** entries
only. It does nothing about the ciphertext that machine can already reach. The
order matters, and so does what you do afterwards.

### When you still have the device

Destroy the on-device secret *first*, while you can, then rotate the recipient
set.

```bash
# 1. On the machine being retired: find and destroy its secret.
gpg --list-secret-keys --with-colons machine@example.invalid   # note the fpr
gpg --delete-secret-keys <FINGERPRINT>

# The agent stores each secret as private-keys-v1.d/<KEYGRIP>.key -- remove any
# that survive. Note that overwriting a file does not reliably destroy it on an
# SSD or a copy-on-write filesystem; the guarantee comes from the next step or
# from destroying the disk encryption key.
```

For a TPM-bound key the strong move is to destroy the wrapping key instead:

```bash
sudo tpm2_clear          # irreversible: destroys the TPM's seeds
```

That makes every TPM-wrapped blob on the machine permanently undecryptable —
including the machine key, whether or not its file still exists. **It also
breaks everything else that TPM protects**, such as a `systemd-cryptenroll` LUKS
enrolment, so it belongs to a machine actually being wiped, not to one being
handed to a colleague.

Then, from a machine that still has access:

```bash
pass init master@example.invalid other-machine@example.invalid   # re-encrypts
```

### When the device is stolen

You cannot destroy the on-device secret. Say so plainly to yourself, because the
temptation is to treat re-encryption as if it fixed something.

- The thief's copy of the store still opens, with every entry as it stood at the
  time of the theft.
- Re-encrypting the canonical store means only that entries changed *afterwards*
  are out of reach.
- **`git` history makes this worse.** A git-backed store keeps every previous
  version of every entry, each still encrypted to the retired key. Re-encrypting
  the working tree leaves all of that readable. Genuinely removing it means
  rewriting history (`git filter-repo`) and force-pushing, and even then any
  clone the thief holds is unaffected.

So re-encryption is containment, not remediation. **Rotate the passwords
themselves** — that is the only step that actually revokes what the machine
could read. Re-keying the store decides who can read the *new* values.

What limits the damage is decided long before the theft: full-disk encryption,
so a powered-off machine yields nothing, and per-subtree `.gpg-id` scoping, so a
machine is only ever a recipient on what it needed.

## What GTKPass does and does not do today

Supported now, and verified rather than assumed:

- Multi-recipient stores. `DirectBackend._recipients_for` returns every
  non-comment line of the nearest `.gpg-id`, and `_encrypt_to_file` encrypts to
  all of them — confirmed by reading back two `pubkey enc packet` records from a
  written entry.
- Per-subtree `.gpg-id`, resolved by walking upward from the entry.
- Re-encryption on move or copy across a `.gpg-id` boundary, when the recipient
  sets differ (`_reencrypt_or_rename`).
- Whatever the host agent uses to unwrap a key. TPM and smartcard both work
  through the existing `--socket=gpg-agent` grant with **no additional sandbox
  permission**: the Flatpak has no `tpm2daemon` and no `/dev/tpm*`, because the
  agent doing the work runs on the host.

Missing, and the reason this is a design note rather than a guide:

- **Re-encrypting a store to a changed recipient set.** `pass init <ids...>` does
  it; `DirectBackend` has no equivalent and there is no interface for it. Every
  enrolment and every retirement above needs a terminal.
- Any view of who a store is currently encrypted to, which is what makes a stale
  recipient noticeable.

Until those exist the model is adoptable but not administrable from GTKPass, and
the retirement steps in particular have to be carried out by hand.
