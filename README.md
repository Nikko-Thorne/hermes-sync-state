# hermes-sync-state

Cross-machine state sync for [Hermes Agent](https://hermes-agent.nousresearch.com) — skills, memories, and cron jobs that follow you everywhere.

## Quick Start

```bash
git clone https://github.com/Nikko-Thorne/hermes-sync-state.git
cd hermes-sync-state
python3 hermes-sync setup    # Interactive TUI — pick your sync method
python3 hermes-sync push      # Upload your state
```

On another machine:
```bash
python3 hermes-sync pull      # Download + decrypt state
```

## Sync Methods

Run `python3 hermes-sync setup` and choose:

| Method | Setup | Privacy |
|--------|-------|---------|
| **Brave Sync** (default) | 24 seed words | E2E encrypted — relay can't read data |
| **Private Git Repo** | Git remote URL | Your repo, your rules |
| **Local Folder** | Path to synced folder | Syncthing, Dropbox, Nextcloud |
| **S3 / R2 Bucket** | Bucket URL + API token | Your own cloud storage |

### Brave Sync (seed phrase)

Zero-config. Generates 24 BIP39 words → derives AES-256 key → encrypts your state → pushes to a Cloudflare R2 relay. The relay sees only encrypted bytes. Anyone with the 24 words can sync.

First, deploy your own relay (one-time):

```bash
cd worker
npx wrangler login
npx wrangler r2 bucket create hermes-sync-blobs
npx wrangler deploy
# Copy the printed URL, e.g. https://your-relay.workers.dev
export HERMES_SYNC_RELAY=https://your-relay.workers.dev
```

Then sync:

```
python3 hermes-sync setup     # pick Brave Sync, save the 24 words
python3 hermes-sync push      # encrypt + upload
# ... on other machine ...
python3 hermes-sync setup     # pick Brave Sync, paste the 24 words
python3 hermes-sync pull      # download + decrypt
```

## What Gets Synced

- `skills/` — Hermes skills (SKILL.md files)
- `memories/` — MEMORY.md, USER.md  
- `cron/` — Cron job definitions

## Security

- **Brave Sync**: AES-256-GCM encryption. Key derived from seed via PBKDF2 (600k iterations). Relay is zero-knowledge.
- **Git**: Your private repo. Treat it like any private git repo.
- **Local**: Files on disk. Whatever your folder sync provides.
- **S3**: Encrypted blob + bearer token auth.

No accounts. No third-party services. Your data, your backend.
