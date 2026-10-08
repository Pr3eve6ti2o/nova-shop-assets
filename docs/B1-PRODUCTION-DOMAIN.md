# B-1: Production Domain Checklist

## What the user must provide
- [ ] A domain name (e.g. `rent.nova.example.com`)
- [ ] DNS A record pointing to the production server IP
- [ ] TLS certificate (Let's Encrypt recommended)

## Configuration (once domain is live)

### 1. Identity service (`nova-platform/nova-private/identity/.env`)
```bash
RENTAL_PUBLIC_BASE_URL=https://<domain>
BETTER_AUTH_URL=https://<domain>
```

### 2. Bot (`nova-bot-test/.env` or production `.env`)
```bash
NOVA_API_URL=https://<domain>
# Must be https:// — the bot now refuses remote http:// (audit 12.2)
```

### 3. Webhook mode (required for multi-tenant)
The bot must switch from polling to webhook mode:
```bash
# In bot config:
WEBHOOK_URL=https://<domain>/webhook/<bot-token-path>
WEBHOOK_ENABLED=1
```

### 4. Verify
- [ ] `curl https://<domain>/api/health` returns 200
- [ ] Bot receives Telegram updates via webhook (not polling)
- [ ] Mini App loads from `https://<domain>`
- [ ] TLS certificate valid (not self-signed)

## Notes
- The website (`:3003`) is currently localhost-only. B-1 unblocks public access.
- Do NOT expose the admin panel (`:3001`) publicly — keep behind firewall/VPN.
