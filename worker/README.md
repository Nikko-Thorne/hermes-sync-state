# Hermes Sync Relay

Cloudflare Worker for the Brave Sync adapter. Stores E2E encrypted blobs in R2.

## Deploy

```bash
npm install -g wrangler
wrangler login
wrangler r2 bucket create hermes-sync-blobs
wrangler deploy
```

## Endpoints

- `PUT /:hash` — Store encrypted blob (max 50MB)
- `GET /:hash` — Retrieve encrypted blob

The worker has zero knowledge of the data — all encryption/decryption happens client-side.
