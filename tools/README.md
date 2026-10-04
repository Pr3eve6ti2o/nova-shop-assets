# Tools

| Script | Purpose |
|---|---|
| `sync_payload_to_bot.py` | Sync catalog edits from Payload CMS → bot SQLite (idempotent, `--dry-run`) |
| `export_catalog.py` | Export catalog JSON for the Mini App bundle (incl. `merchant_ton_address`) |
| `build_miniapp_bundle.py` | Assemble `miniapp/dist/index.html` from source |
| `notify_restock.py` | DM users with stock alerts when items restock |
| `sync_payload_to_bot.py` | (see above) detects restocks (0→>0) for alerts |
| `make_wallet.py` / `hdwallet-gen/` | HD wallet generation via Trust Wallet wallet-core |
| `decrypt_seed.py` | Decrypt the AES-256-GCM seed backup |
| `export_policies.py` | Export bot legal texts |

All scripts are safe to re-run. Catalog pipeline: Payload edit → `sync_payload_to_bot.py` → `export_catalog.py` → `build_miniapp_bundle.py` → publish.
