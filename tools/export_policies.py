#!/usr/bin/env python3
"""Export bot policy texts to miniapp/policies.json for the web footer.

Pulls MSG_TERMS, MSG_PRIVACY, MSG_REFUND from texts.py (single source of
truth lives in the bot). Strips Telegram HTML tags for web rendering —
the Mini App renders them as plain text sections.

Usage:
    python3 tools/export_policies.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import texts  # noqa: E402


def clean(html: str) -> str:
    # <b>, <i>, <code>, <a> -> plain text; <br>/\n preserved.
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</p\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main() -> int:
    out = {
        "terms": {"title": "Terms of Service", "body": clean(texts.MSG_TERMS)},
        "privacy": {"title": "Privacy Policy", "body": clean(texts.MSG_PRIVACY)},
        "refunds": {"title": "Refund Policy", "body": clean(texts.MSG_REFUND)},
    }
    path = os.path.join(ROOT, "miniapp", "policies.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"exported policies -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
