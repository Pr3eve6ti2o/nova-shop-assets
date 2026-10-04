#!/usr/bin/env python3
"""Build a single-file Mini App bundle for the hosted static artifact.

The hosted web_static runtime serves index.html (+ files under assets/) and
forbids browser local-storage APIs, so the multi-file miniapp/ source is
bundled into ONE self-contained miniapp/dist/index.html:

  - styles.css  -> inlined <style>
  - catalog.json -> inlined as window.NOVA_CATALOG (app.js prefers it over fetch)
  - app.js      -> inlined <script> (localStorage-free; uses Telegram CloudStorage)

Source of truth stays miniapp/index.html + styles.css + app.js + catalog.json.
Re-run after every Mini App change, then push dist/index.html to the artifact.

Usage:
    python3 tools/build_miniapp_bundle.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "miniapp")
DIST = os.path.join(SRC, "dist")


def read(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return f.read()


def main() -> int:
    html = read("index.html")
    css = read("styles.css")
    js = read("app.js")
    catalog = json.loads(read("catalog.json"))

    # Inline the stylesheet.
    link_tag = '<link rel="stylesheet" href="styles.css">'
    if link_tag not in html:
        print(f"ERROR: expected {link_tag!r} in index.html", file=sys.stderr)
        return 1
    # Guard against a literal </style> inside the CSS.
    css_safe = css.replace("</style", "<\\/style")
    html = html.replace(link_tag, "<style>\n" + css_safe + "\n</style>")

    # Inline the catalog data BEFORE the app script.
    catalog_json = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    catalog_tag = ('<script>window.NOVA_CATALOG='
                   + catalog_json.replace("</script", "<\\/script")
                   + ";</script>")

    # Inline the policies (footer sheets) BEFORE the app script.
    policies = json.loads(read("policies.json"))
    policies_json = json.dumps(policies, ensure_ascii=False, separators=(",", ":"))
    policies_tag = ('<script>window.NOVA_POLICIES='
                    + policies_json.replace("</script", "<\\/script")
                    + ";</script>")

    # Inline the app script (escape any literal </script> inside strings).
    script_tag = '<script src="app.js"></script>'
    if script_tag not in html:
        print(f"ERROR: expected {script_tag!r} in index.html", file=sys.stderr)
        return 1
    js_safe = js.replace("</script", "<\\/script")
    html = html.replace(script_tag, policies_tag + "\n" + catalog_tag + "\n<script>\n" + js_safe + "\n</script>")

    # Sanity: no external local refs may remain (telegram-web-app.js is allowed).
    for bad in ('href="styles.css"', 'src="app.js"', '"catalog.json"'):
        if bad in html and 'telegram-web-app.js' not in bad:
            # "catalog.json" string remains in the fetch fallback — that is fine.
            if bad == '"catalog.json"':
                continue
            print(f"ERROR: unbundled reference remains: {bad}", file=sys.stderr)
            return 1
    if "localStorage" in html:
        print("ERROR: localStorage reference remains in bundle", file=sys.stderr)
        return 1

    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    n_prods = len(catalog.get("products", []))
    print(f"bundled {n_prods} products -> {out} ({os.path.getsize(out)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
