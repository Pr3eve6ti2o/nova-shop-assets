# Changelog

All notable changes to Nova Shop are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Docker packaging: `Dockerfile` + `docker-compose.yml` (SQLite on a named volume).
- `.env.example` documenting every environment variable the bot reads.
- `Makefile` with install/run/test/lint/docker targets.
- `CONTRIBUTING.md` with branch, commit, and testing conventions.

## [2026-10-13] — Deep-audit fix programme complete

### Fixed
- All P0/P1 findings from the third Opus deep audit of
  `refactor/nova-shop-professional` (atomic checkout/fulfilment, dual-control
  token swaps, EVM deposit identity, Stars enforcement, outbox pattern,
  versioned migrations, inventory reservations).
- `cb()` callback validation relaxed to allow namespaced prefixes (e.g.
  `ad:ord`), fixing an Admin-button crash; regression test added.

### Changed
- Rental UI: Monthly $8.99 / Yearly $89.99 behind "Continue to Payment";
  7-day first-time-only trial; recurring billing via balance auto-debit and
  CryptoBot invoices.
