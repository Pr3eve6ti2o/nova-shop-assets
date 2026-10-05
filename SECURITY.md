# Security Policy

Nova Shop handles customer data, order state and payment information. Treat the repository as security-sensitive application code.

## Never commit

- bot tokens;
- provider/API keys;
- Payload secrets;
- Telegram admin credentials;
- database files;
- wallet mnemonics/private keys;
- xprv/zprv or equivalent private extended keys;
- recovery keys or encrypted backup artifacts.

## Reporting

Do not publish exploitable private details in a public issue. Report security problems through a private maintainer-controlled channel.

## Scope

Security properties for checkout, payment verification and wallet infrastructure are described in docs/SECURITY.md and docs/AUDIT-2026-10-05.md.

An open-source codebase is not automatically audited or production-safe.
