# Deployment

## Bot (systemd)

```bash
# Install the unit (canonical copy in bot/nova-shop.service)
sudo cp bot/nova-shop.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nova-shop
```

The unit loads env from `.env` (+ `.proxy.env` for the sandbox egress proxy, refreshed minutely by cron).

## Admin panel (systemd)

```bash
cd admin && npm install && npm run build
sudo cp admin/nova-shop-admin.service /etc/systemd/system/  # if present
sudo systemctl enable --now nova-shop-admin   # → http://localhost:3001/admin
```

## Mini App

1. Rebuild: `python tools/export_catalog.py && python tools/build_miniapp_bundle.py`
2. Publish `miniapp/dist/index.html` as the bot's Mini App (BotFather `/newapp`).
3. TON Connect manifest is served via jsDelivr from this repo's `tonconnect/` dir.

## VM replacement note

`/etc/systemd/system` is ephemeral on this host — after a VM replacement, reinstall both units from the repo copies and `daemon-reload`.

## Backups

- Seed: AES-256-GCM encrypted (`tools/decrypt_seed.py` to recover).
- DB: `data/*.db` — back up regularly; never commit.
