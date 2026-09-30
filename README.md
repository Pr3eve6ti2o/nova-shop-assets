# Nova Shop Assets

Static assets for the [Nova Shop](https://t.me/testssscbot) Telegram Mini App.

Served via [jsDelivr](https://www.jsdelivr.com/) CDN for fast global delivery.

## Structure

```
nova-shop-assets/
├── tonconnect/
│   ├── tonconnect-manifest.json  # TON Connect dApp manifest
│   └── nova-icon-180.png         # 180×180 wallet icon (PNG, required by TON Connect)
├── brand/
│   └── nova-icon-180.png         # Brand icon (same file, canonical location)
└── docs/
```

## TON Connect

The manifest is served at:
```
https://cdn.jsdelivr.net/gh/Pr3eve6ti2o/nova-shop-assets/tonconnect/tonconnect-manifest.json
```

Wallets fetch this to display the dApp name and icon when users connect.
See [TON Connect docs](https://docs.ton.org/develop/dapps/ton-connect/manifest) for the manifest spec.

### Updating the manifest

1. Edit `tonconnect/tonconnect-manifest.json`
2. Commit and push — jsDelivr picks up changes within minutes
3. Note: wallets cache the manifest up to 24h; version the filename during development

## License

All assets © Nova Shop. All rights reserved.
