/* ============================================================
   Nova Shop Mini App — storefront SPA (no build step).
   Data: catalog.json (see tools/export_catalog.py).
   Checkout: window.Telegram.WebApp.sendData({items:[{id,qty}], promo})
   (<=4096 bytes) -> the bot re-validates everything server-side.
   Prices NEVER come from the client.
   Cart persistence: in-memory + Telegram CloudStorage only.
   Browser client-side storage APIs are intentionally NEVER used —
   the hosted runtime forbids them.
   ============================================================ */
(function () {
  "use strict";

  /* ---------------- environment ---------------- */
  var tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
  var IN_TG = !!tg;
  var CURRENCY = window.NOVA_CURRENCY || "USD";
  var CART_KEY = "nova_shop_cart_v1";
  var WISH_KEY = "nova_shop_wish_v1";
  var SEARCH_KEY = "nova_shop_search_v1";
  var ALERT_KEY = "nova_shop_stock_alerts_v1";
  var ALERT_SYNC_KEY = "nova_shop_alert_sync_v1";
  var SENDDATA_LIMIT = 4096;

  /* Version-gated Telegram APIs (never assume a method exists). */
  function atLeast(v) {
    try { return !!(tg && typeof tg.isVersionAtLeast === "function" && tg.isVersionAtLeast(v)); }
    catch (e) { return false; }
  }

  /* ---------------- tiny dom helpers ---------------- */
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var moneyFmt = null;
  try { moneyFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: CURRENCY }); } catch (e) { /* fallback below */ }
  function money(cents) {
    var v = (Number(cents) || 0) / 100;
    if (moneyFmt) { try { return moneyFmt.format(v); } catch (e) { /* fallthrough */ } }
    return "$" + v.toFixed(2);
  }

  /* ---------------- inline SVG icons (no emoji in chrome) ---------------- */
  var IC = {
    cart: '<circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>',
    search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    back: '<polyline points="15 18 9 12 15 6"/>',
    star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    minus: '<line x1="5" y1="12" x2="19" y2="12"/>',
    check: '<polyline points="20 6 9 17 4 12"/>',
    trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    tag: '<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>',
    box: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>',
    zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    truck: '<rect x="1" y="3" width="15" height="13" rx="1"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>',
    info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    alert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    refresh: '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
    heart: '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
    filter: '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>',
    bell: '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    flame: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
    chevron: '<polyline points="6 9 12 15 18 9"/>'
  };
  function icon(name, cls) {
    var filled = name === "star";
    return '<svg class="ic ' + (cls || "") + '" viewBox="0 0 24 24" aria-hidden="true" ' +
      (filled ? 'fill="currentColor" stroke="none"' : 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"') +
      ">" + IC[name] + "</svg>";
  }

  /* ---------------- haptics (guarded) ---------------- */
  function buzz(kind) {
    try { if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred(kind || "light"); } catch (e) {}
  }
  function chirp(type) {
    try { if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(type || "success"); } catch (e) {}
  }

  /* ---------------- toasts ----------------
     Success = past tense, auto-dismiss. Errors NEVER auto-dismiss —
     they say what happened + the next step; tap to dismiss.
     Destructive actions offer Undo. */
  function toast(msg, kind, opts) {
    opts = opts || {};
    var box = $("toasts");
    if (!box) return;
    var t = document.createElement("div");
    t.className = "toast " + (kind || "info");
    var dot = document.createElement("span");
    dot.className = "toast-dot";
    var label = document.createElement("span");
    label.textContent = msg;
    t.appendChild(dot);
    t.appendChild(label);
    var timer = null;
    function dismiss() {
      if (timer) { clearTimeout(timer); timer = null; }
      t.classList.remove("show");
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 300);
    }
    if (opts.action) {
      var b = document.createElement("button");
      b.className = "toast-action";
      b.textContent = opts.action.label;
      b.addEventListener("click", function (ev) {
        ev.stopPropagation();
        dismiss();
        try { opts.action.fn(); } catch (e) {}
      });
      t.appendChild(b);
    }
    if (kind === "error") {
      t.setAttribute("role", "alert");
      t.addEventListener("click", dismiss); // tap a persistent error to dismiss it
    } else {
      timer = setTimeout(dismiss, opts.action ? 5000 : 2600);
    }
    box.appendChild(t);
    while (box.children.length > 3) box.removeChild(box.firstChild);
    requestAnimationFrame(function () { t.classList.add("show"); });
  }

  /* ---------------- state ---------------- */
  var S = {
    categories: [],
    products: [],
    byId: {},
    cat: "all",          // "all" or category id
    query: "",
    sort: "featured",    // featured | price-asc | price-desc | rating
    cart: {},            // productId -> qty
    promo: "",
    promoOpen: false,
    recent: [],          // recently viewed product ids (in-memory, max 8)
    wish: {},            // wishlist: productId -> true (CloudStorage persisted)
    stockAlerts: {},     // out-of-stock notify-me: productId -> true
    filters: {           // Phase 2: catalog filters
      maxPrice: 0,       // 0 = no limit (cents)
      inStock: false,
      onSale: false,
      minRating: 0       // 0 = any
    },
    recentSearches: [],  // recent search terms (CloudStorage persisted, max 6)
    view: "home",        // home | cart | success
    sheet: null,         // {mode:"product"|"sort", id, qty}
    loading: true,
    loadError: false,
    actionLoading: false,
    lastFocus: null
  };

  var SORTS = [
    { id: "featured", label: "Recommended" },
    { id: "price-asc", label: "Cheapest first" },
    { id: "price-desc", label: "Most expensive" },
    { id: "rating", label: "Top rated" }
  ];
  function sortLabel() {
    for (var i = 0; i < SORTS.length; i++) {
      if (SORTS[i].id === S.sort) return SORTS[i].label;
    }
    return SORTS[0].label;
  }

  /* Cart persistence: in-memory for the session, plus Telegram CloudStorage
     (the Telegram-native per-user store, Bot API 6.9+) when available. */
  var tgCloud = null;
  try {
    tgCloud = (tg && tg.CloudStorage && atLeast("6.9")) ? tg.CloudStorage : null;
  } catch (e) { tgCloud = null; }
  function saveCart() {
    if (!tgCloud) return;
    try {
      tgCloud.setItem(CART_KEY, JSON.stringify({ items: S.cart, promo: S.promo }), function () {});
    } catch (e) {}
  }
  function restoreCart(raw) {
    var d = null;
    try { d = JSON.parse(raw || "null"); } catch (e) { return; }
    if (!d || typeof d !== "object") return;
    if (d.items && typeof d.items === "object") {
      Object.keys(d.items).forEach(function (id) {
        var q = Math.floor(Number(d.items[id]));
        if (q > 0 && q <= 99) S.cart[id] = q;
      });
    }
    if (typeof d.promo === "string") S.promo = d.promo.toUpperCase().slice(0, 32);
  }
  function loadCart() {
    if (!tgCloud) return;
    try {
      tgCloud.getItem(CART_KEY, function (err, raw) {
        if (err || !raw) return;
        restoreCart(raw);
        pruneCart();
        render();
      });
    } catch (e) {}
  }

  /* Wishlist + recent searches: same CloudStorage pattern as the cart. */
  function saveWish() {
    if (!tgCloud) return;
    try {
      tgCloud.setItem(WISH_KEY, JSON.stringify({ ids: Object.keys(S.wish) }), function () {});
    } catch (e) {}
  }
  function loadWish() {
    if (!tgCloud) return;
    try {
      tgCloud.getItem(WISH_KEY, function (err, raw) {
        if (err || !raw) return;
        var d = null;
        try { d = JSON.parse(raw); } catch (e) { return; }
        // C2: don't validate against S.byId here — catalog may not be loaded
        // yet. Raw IDs are pruned in applyCatalog via pruneWish().
        (d.ids || []).forEach(function (id) { S.wish[id] = true; });
        render();
      });
    } catch (e) {}
  }
  function pruneWish() {
    // Drop wishlist IDs that don't exist in the loaded catalog.
    Object.keys(S.wish).forEach(function (id) {
      if (!S.byId[id]) delete S.wish[id];
    });
  }
  function saveSearches() {
    if (!tgCloud) return;
    try {
      tgCloud.setItem(SEARCH_KEY, JSON.stringify({ q: S.recentSearches.slice(0, 6) }), function () {});
    } catch (e) {}
  }
  function loadSearches() {
    if (!tgCloud) return;
    try {
      tgCloud.getItem(SEARCH_KEY, function (err, raw) {
        if (err || !raw) return;
        var d = null;
        try { d = JSON.parse(raw); } catch (e) { return; }
        if (d.q && d.q.length) S.recentSearches = d.q.slice(0, 6);
      });
    } catch (e) {}
  }
  function pushRecentSearch(term) {
    term = term.slice(0, 40);
    S.recentSearches = [term].concat(S.recentSearches.filter(function (t) { return t !== term; })).slice(0, 6);
    saveSearches();
  }
  function renderSuggest() {
    var box = $("search-suggest");
    var q = $("search").value.trim().toLowerCase();
    var html = "";
    // matching product names as you type
    if (q.length >= 2) {
      var matches = S.products.filter(function (p) {
        return (p.name || "").toLowerCase().indexOf(q) !== -1;
      }).slice(0, 5);
      if (matches.length) {
        html += '<div class="suggest-group-label">Products</div>' + matches.map(function (p) {
          return '<button class="suggest-item" data-action="suggest-product" data-id="' + p.id + '">' +
            icon("search") + "<span>" + esc(p.name) + "</span></button>";
        }).join("");
      }
    } else {
      // recent searches
      if (S.recentSearches.length) {
        html += '<div class="suggest-group-label">Recent</div>' + S.recentSearches.map(function (t) {
          return '<button class="suggest-item" data-action="suggest-term" data-id="' + esc(t) + '">' +
            icon("search") + "<span>" + esc(t) + "</span></button>";
        }).join("");
      }
      // popular searches (top-rated products)
      var popular = S.products.slice().sort(function (a, b) {
        return ((b.rating || 0) * (b.reviews || 0)) - ((a.rating || 0) * (a.reviews || 0));
      }).slice(0, 4);
      if (popular.length) {
        html += '<div class="suggest-group-label">Popular</div>' + popular.map(function (p) {
          return '<button class="suggest-item" data-action="suggest-product" data-id="' + p.id + '">' +
            icon("flame") + "<span>" + esc(p.name) + "</span></button>";
        }).join("");
      }
      // popular categories
      html += '<div class="suggest-group-label">Browse</div>' + S.categories.slice(0, 4).map(function (c) {
        return '<button class="suggest-item" data-action="suggest-cat" data-id="' + esc(c.id) + '">' +
          icon("tag") + "<span>" + esc((c.emoji ? c.emoji + " " : "") + c.name) + "</span></button>";
      }).join("");
    }
    box.innerHTML = html;
    box.hidden = !html;
  }

  function toggleWish(id) {
    if (S.wish[id]) { delete S.wish[id]; toast("Removed from wishlist.", "info"); }
    else { S.wish[id] = true; toast("Saved to wishlist.", "success"); }
    saveWish();
    buzz("light");
    render();
    // M2: refresh the open sheet too, so its heart button reflects the toggle.
    if (S.sheet) renderSheet();
  }
  function toggleStockAlert(id) {
    var alerts = S.stockAlerts || {};
    var turningOn = !alerts[id];
    if (turningOn) {
      alerts[id] = true;
      toast("We'll notify you when it's back in stock.", "success");
    } else {
      delete alerts[id];
      toast("Stock alert removed.", "info");
    }
    S.stockAlerts = alerts;
    if (tgCloud) {
      try { tgCloud.setItem(ALERT_KEY, JSON.stringify({ ids: Object.keys(alerts) }), function () {}); } catch (e) {}
    }
    // Sync to bot so it can DM when stock returns (best-effort, non-blocking).
    // C3: tg.sendData() CLOSES the Mini App, so fire-and-forget sync is out.
    // Queue the change; it piggybacks on the next checkout payload.
    S.pendingAlertSync = S.pendingAlertSync || {};
    S.pendingAlertSync[id] = turningOn;
    if (tgCloud) {
      try { tgCloud.setItem(ALERT_SYNC_KEY, JSON.stringify(S.pendingAlertSync), function () {}); } catch (e) {}
    }
    buzz("light");
    renderSheet();
  }

  /* ---------------- catalog ---------------- */
  function fetchCatalog() {
    S.loading = true;
    S.loadError = false;
    render();
    var t0 = Date.now();
    // Single-file hosted build inlines the catalog as window.NOVA_CATALOG.
    if (typeof window !== "undefined" && window.NOVA_CATALOG) {
      var wait = Math.max(0, 450 - (Date.now() - t0));
      setTimeout(function () { applyCatalog(window.NOVA_CATALOG || {}); }, wait);
      return;
    }
    fetch("catalog.json", { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        // keep skeletons visible briefly for a polished feel
        var wait = Math.max(0, 450 - (Date.now() - t0));
        setTimeout(function () { applyCatalog(data || {}); }, wait);
      })
      .catch(function () {
        S.loading = false;
        S.loadError = true;
        render();
      });
  }
  function applyCatalog(data) {
    S.categories = Array.isArray(data.categories) ? data.categories : [];
    S.products = (Array.isArray(data.products) ? data.products : []).map(function (p) {
      p.rating = p.reviews > 0 ? (Number(p.rating_sum) || 0) / p.reviews : 0;
      return p;
    });
    S.byId = {};
    S.products.forEach(function (p) { S.byId[p.id] = p; });
    if (data.merchant_ton_address) TON_MERCHANT = String(data.merchant_ton_address);
    pruneCart();
    pruneWish();
    loadRecent();
    S.loading = false;
    S.loadError = false;
    render();
  }
  function pruneCart() {
    // C1: never prune before the catalog is loaded — S.byId is empty then
    // and every restored item would be deleted + persisted as empty.
    if (!S.products.length) return;
    var dropped = 0, changed = false;
    Object.keys(S.cart).forEach(function (id) {
      var p = S.byId[id];
      if (!p || p.stock === 0) {
        delete S.cart[id]; changed = true; dropped++;
        return;
      }
      var max = maxQty(p);
      if (S.cart[id] > max) { S.cart[id] = max; changed = true; }
    });
    if (changed) {
      saveCart();
      if (dropped > 0) toast("Some items were removed because they are no longer available.", "info");
    }
  }

  /* ---------------- derived helpers ---------------- */
  function maxQty(p) { return p.stock === -1 ? 99 : Math.max(0, Math.min(99, Number(p.stock) || 0)); }
  function isDigital(p) { return p.kind === "digital" || p.stock === -1; }
  function cartCount() {
    var n = 0;
    Object.keys(S.cart).forEach(function (id) { n += S.cart[id]; });
    return n;
  }
  function cartSubtotal() {
    var t = 0;
    Object.keys(S.cart).forEach(function (id) {
      var p = S.byId[id];
      if (p) t += (Number(p.price_cents) || 0) * S.cart[id];
    });
    return t;
  }
  function catEmoji(catId) {
    for (var i = 0; i < S.categories.length; i++) {
      if (String(S.categories[i].id) === String(catId)) return S.categories[i].emoji || "";
    }
    return "";
  }
  function catName(catId) {
    for (var i = 0; i < S.categories.length; i++) {
      if (String(S.categories[i].id) === String(catId)) return S.categories[i].name || "";
    }
    return "";
  }
  /* Per-product icon: catalog `icon` field wins, else a keyword map,
     else the category emoji. (Category emoji alone is wrong per product.) */
  var ICON_KEYWORDS = [
    [/earbuds|earphones|headphones|headset|airpods/i, "🎧"],
    [/charger|cable|usb|adapter/i, "🔌"],
    [/power bank|powerbank|battery/i, "🔋"],
    [/vpn|proxy/i, "🛡️"],
    [/asset|icon pack|template|bundle/i, "🎨"],
    [/wallet/i, "👛"],
    [/stand|holder|dock/i, "📱"],
    [/watch/i, "⌚"],
    [/keyboard|mouse/i, "⌨️"],
    [/speaker|soundbar/i, "🔈"],
    [/lamp|light/i, "💡"],
    [/camera/i, "📷"]
  ];
  function iconFor(p) {
    if (p.icon) return p.icon;
    var n = (p.name || "") + " " + (p.description || "");
    for (var i = 0; i < ICON_KEYWORDS.length; i++) {
      if (ICON_KEYWORDS[i][0].test(n)) return ICON_KEYWORDS[i][1];
    }
    return catEmoji(p.category_id) || "🛍️";
  }
  function offPct(p) {
    var old = Number(p.old_price_cents) || 0, now = Number(p.price_cents) || 0;
    if (old > now && now > 0) return Math.round((1 - now / old) * 100);
    return 0;
  }
  function ratingText(p) {
    if (!(p.reviews > 0)) return "";
    return p.rating.toFixed(1) + " · " + p.reviews + (p.reviews === 1 ? " review" : " reviews");
  }
  function hueFor(id) {
    var n = parseInt(id, 10);
    if (isNaN(n)) n = String(id).length * 37;
    return ((n * 137) % 360 + 360) % 360;
  }
  function stockMeta(p) {
    if (p.stock === -1) return { label: "Digital delivery", tone: "ok" };
    if (p.stock === 0) return { label: "Out of stock", tone: "bad" };
    if (p.stock <= 5) return { label: "Only " + p.stock + " left", tone: "warn" };
    return { label: "In stock", tone: "ok" };
  }
  function filteredProducts() {
    var q = S.query.trim().toLowerCase();
    var f = S.filters;
    return S.products.filter(function (p) {
      if (S.cat !== "all" && String(p.category_id) !== String(S.cat)) return false;
      if (S.cat === "wishlist" && !S.wish[p.id]) return false;
      if (q && ((p.name || "") + " " + (p.description || "")).toLowerCase().indexOf(q) === -1) return false;
      if (f.maxPrice > 0 && Number(p.price_cents) > f.maxPrice) return false;
      if (f.inStock && p.stock === 0) return false;
      if (f.onSale && !(Number(p.old_price_cents) > Number(p.price_cents))) return false;
      if (f.minRating > 0 && !(Number(p.rating) >= f.minRating)) return false;
      return true;
    });
  }
  function activeFilterCount() {
    var f = S.filters, n = 0;
    if (f.maxPrice > 0) n++;
    if (f.inStock) n++;
    if (f.onSale) n++;
    if (f.minRating > 0) n++;
    return n;
  }
  function sortedProducts(list) {
    var arr = list.slice();
    if (S.sort === "price-asc") {
      arr.sort(function (a, b) { return (Number(a.price_cents) || 0) - (Number(b.price_cents) || 0); });
    } else if (S.sort === "price-desc") {
      arr.sort(function (a, b) { return (Number(b.price_cents) || 0) - (Number(a.price_cents) || 0); });
    } else if (S.sort === "rating") {
      arr.sort(function (a, b) {
        return (b.rating - a.rating) || ((b.reviews || 0) - (a.reviews || 0));
      });
    }
    return arr;
  }
  function relatedProducts(p) {
    return S.products
      .filter(function (x) { return x.id !== p.id && String(x.category_id) === String(p.category_id) && x.stock !== 0; })
      .sort(function (a, b) { return (b.reviews || 0) - (a.reviews || 0); })
      .slice(0, 6);
  }
  function bundleProducts(p) {
    // "Frequently bought together": top in-stock product from a different category
    var others = S.products.filter(function (x) {
      return x.id !== p.id && String(x.category_id) !== String(p.category_id) && x.stock !== 0;
    }).sort(function (a, b) { return (b.rating * (b.reviews || 0)) - (a.rating * (a.reviews || 0)); });
    return others.slice(0, 1);
  }
  function bundleHTML(p) {
    var buddies = bundleProducts(p);
    if (!buddies.length || p.stock === 0) return "";
    var b = buddies[0];
    var total = Number(p.price_cents) + Number(b.price_cents);
    return '<div class="bundle-wrap"><h2 class="section-title">Frequently bought together</h2>' +
      '<div class="bundle-items">' +
      '<button class="bundle-item" data-action="open-product" data-id="' + p.id + '">' +
      '<span class="bundle-emoji">' + esc(iconFor(p)) + "</span><span>" + esc(p.name) + "</span>" +
      "<b>" + money(p.price_cents) + "</b></button>" +
      '<span class="bundle-plus" aria-hidden="true">+</span>' +
      '<button class="bundle-item" data-action="open-product" data-id="' + b.id + '">' +
      '<span class="bundle-emoji">' + esc(iconFor(b)) + "</span><span>" + esc(b.name) + "</span>" +
      "<b>" + money(b.price_cents) + "</b></button>" +
      "</div>" +
      '<button class="btn primary btn-block" data-action="bundle-add" data-id="' + p.id + "|" + b.id + '">' +
      "Add both to cart · " + money(total) + "</button></div>";
  }
  function bestsellers() {
    return S.products
      .filter(function (x) { return x.stock !== 0; })
      .sort(function (a, b) { return (b.rating * (b.reviews || 0)) - (a.rating * (a.reviews || 0)); })
      .slice(0, 3);
  }
  var RECENT_KEY = "nova_shop_recent_v1";
  function pushRecent(id) {
    id = String(id);
    S.recent = S.recent.filter(function (x) { return x !== id; });
    S.recent.unshift(id);
    if (S.recent.length > 12) S.recent.length = 12;
    if (tgCloud) {
      try { tgCloud.setItem(RECENT_KEY, JSON.stringify({ ids: S.recent }), function () {}); } catch (e) {}
    }
  }
  function loadRecent() {
    if (!tgCloud) return;
    try {
      tgCloud.getItem(RECENT_KEY, function (err, raw) {
        if (err || !raw) return;
        var d = null;
        try { d = JSON.parse(raw); } catch (e) { return; }
        if (d.ids && d.ids.length) {
          S.recent = d.ids.filter(function (id) { return S.byId[id]; }).slice(0, 12);
          render();
        }
      });
    } catch (e) {}
  }

  /* ---------------- render: product visuals & cards ----------------
     Card anatomy (marketplace playbook): visual -> name (2-line clamp)
     -> rating chip -> price row (bold + struck + % off).
     Whole card opens the product sheet; quick-add is a separate
     44px focusable control. */
  function visualHTML(p, size, opts) {
    opts = opts || {};
    var h = hueFor(p.id);
    var h2 = (h + 45) % 360;
    var art;
    if (p.photo_url) {
      art = '<img src="' + esc(p.photo_url) + '" alt="" style="width:100%;height:100%;object-fit:cover;position:absolute;inset:0;">';
    } else {
      art = '<span class="vis-emoji" aria-hidden="true">' + esc(iconFor(p)) + "</span>";
    }
    var html = '<div class="visual visual-' + size + '" style="background:linear-gradient(135deg,hsl(' +
      h + ',62%,56%),hsl(' + h2 + ',62%,42%))">';
    if (opts.badges !== false) {
      html += '<span class="kind-badge">' + (isDigital(p) ? "DIGITAL" : "PHYSICAL") + "</span>";
      var off = offPct(p);
      if (off) html += '<span class="off-badge">-' + off + "%</span>";
    }
    html += art;
    if (p.stock === 0) html += '<span class="oos-veil">Out of stock</span>';
    if (opts.quickAdd) {
      html += '<button class="quick-add" data-action="add" data-id="' + p.id +
        '" aria-label="Quick add ' + esc(p.name) + ' to cart">' + icon("plus") + "</button>";
    }
    if (opts.wish !== false) {
      var wished = !!S.wish[p.id];
      html += '<button class="wish-btn' + (wished ? " is-wished" : "") + '" data-action="wish" data-id="' + p.id +
        '" aria-label="' + (wished ? "Remove " : "Save ") + esc(p.name) +
        (wished ? " from wishlist" : " to wishlist") + '" aria-pressed="' + wished + '">' +
        icon("heart") + "</button>";
    }
    return html + "</div>";
  }

  function ratingHTML(p) {
    if (p.reviews > 0) {
      return '<span class="rating">' + icon("star", "ic-xs") + "<b>" + p.rating.toFixed(1) +
        "</b><span>&nbsp;·&nbsp;" + p.reviews + (p.reviews === 1 ? " review" : " reviews") + "</span></span>";
    }
    return '<span class="rating new">New</span>';
  }

  function cardHTML(p) {
    var sm = stockMeta(p);
    var oos = p.stock === 0;
    var old = offPct(p) > 0 ? '<s class="old">' + money(p.old_price_cents) + "</s>" : "";
    return '<article class="card' + (oos ? " is-oos" : "") + '" role="button" tabindex="0" ' +
      'data-action="open" data-id="' + p.id + '" ' +
      'aria-label="' + esc(p.name) + ", " + money(p.price_cents) + '">' +
      visualHTML(p, "md", { quickAdd: !oos }) +
      '<div class="card-body">' +
        '<h3 class="card-name">' + esc(p.name) + "</h3>" +
        '<div class="card-meta">' + ratingHTML(p) +
          '<span class="stock s-' + sm.tone + '">' + esc(sm.label) + "</span></div>" +
        '<div class="card-price"><span class="price">' + money(p.price_cents) + "</span>" + old + "</div>" +
      "</div></article>";
  }

  function railCardHTML(p) {
    return '<button class="rail-card" data-action="open" data-id="' + p.id + '" ' +
      'aria-label="' + esc(p.name) + ", " + money(p.price_cents) + '">' +
      visualHTML(p, "rail", { badges: false }) +
      '<div class="rail-name">' + esc(p.name) + "</div>" +
      '<div class="rail-price">' + money(p.price_cents) + "</div></button>";
  }

  function skeletonHTML(n) {
    var out = "";
    for (var i = 0; i < n; i++) {
      out += '<div class="skel-card" aria-hidden="true"><div class="skel-visual shimmer"></div>' +
        '<div class="skel-line shimmer"></div><div class="skel-line short shimmer"></div></div>';
    }
    return out;
  }

  /* ---------------- render: home ---------------- */
  function emptyStateHTML(art, title, text, btnLabel, action) {
    return '<div class="empty-state"><div class="empty-art">' + icon(art) + "</div>" +
      "<h3>" + esc(title) + "</h3><p>" + esc(text) + "</p>" +
      (btnLabel ? '<button class="btn primary" data-action="' + action + '">' + esc(btnLabel) + "</button>" : "") +
      "</div>";
  }

  function renderHome() {
    // chips
    var ch = '<button class="chip' + (S.cat === "all" ? " is-on" : "") +
      '" data-action="chip" data-cat="all" role="tab" aria-selected="' + (S.cat === "all") + '">All</button>';
    S.categories.forEach(function (c) {
      var on = String(S.cat) === String(c.id);
      ch += '<button class="chip' + (on ? " is-on" : "") + '" data-action="chip" data-cat="' + esc(c.id) +
        '" role="tab" aria-selected="' + on + '">' + esc((c.emoji ? c.emoji + " " : "") + c.name) + "</button>";
    });
    var wishN = Object.keys(S.wish).length;
    ch += '<button class="chip' + (S.cat === "wishlist" ? " is-on" : "") +
      '" data-action="chip" data-cat="wishlist" role="tab" aria-selected="' + (S.cat === "wishlist") + '">' +
      icon("heart", "ic-xs") + " Wishlist" + (wishN ? " (" + wishN + ")" : "") + "</button>";
    $("chips").innerHTML = ch;

    // recently viewed rail (in-memory only)
    var rw = $("recent-wrap");
    var recents = S.recent.map(function (id) { return S.byId[id]; })
      .filter(function (p) { return !!p; });
    if (!S.loading && recents.length > 0) {
      rw.hidden = false;
      $("recent-rail").innerHTML = recents.map(railCardHTML).join("");
    } else {
      rw.hidden = true;
    }

    // toolbar: section title + sort trigger
    var title = "All products";
    if (S.query.trim()) title = 'Results for "' + S.query.trim() + '"';
    else if (S.cat !== "all") title = catName(S.cat) || "Products";
    var list = sortedProducts(filteredProducts());
    title += " · " + list.length + (list.length === 1 ? " item" : " items");
    $("grid-title").textContent = title;
    $("sort-label").textContent = sortLabel();

    // grid / states
    var grid = $("grid"), state = $("grid-state");
    if (S.loading) {
      grid.innerHTML = skeletonHTML(6);
      grid.hidden = false;
      state.hidden = true;
      return;
    }
    if (S.loadError) {
      grid.hidden = true;
      state.hidden = false;
      state.innerHTML = emptyStateHTML("alert", "Couldn't load the catalog",
        "Check your connection and try again.", "Try again", "retry");
      return;
    }
    if (S.products.length === 0) {
      grid.hidden = true;
      state.hidden = false;
      state.innerHTML = emptyStateHTML("box", "The store is being stocked",
        "New products are on the way. Please check back soon.", "Try again", "retry");
      return;
    }
    if (list.length === 0) {
      grid.hidden = true;
      state.hidden = false;
      if (S.query.trim()) {
        // ONE heading only (QA): the h3 carries the query; no stacked h2+h3.
        state.innerHTML = emptyStateHTML("search", "No results for \"" + S.query.trim() + "\"",
          "Try a different search term or browse the categories.", "Clear search", "clear-search");
      } else {
        var msg = "Nothing here yet", sub = "Try a different category or clear your filters.";
        if (S.cat === "wishlist") {
          msg = "Your wishlist is empty";
          sub = "Tap the heart on any product to save it here for later.";
        } else if (activeFilterCount()) {
          msg = "No products match your filters";
          sub = "Try widening the price range or clearing a filter.";
        }
        state.innerHTML = emptyStateHTML("box", msg, sub,
          (S.cat === "wishlist" || activeFilterCount()) ? "Browse all" : "", "chip-all");
      }
      return;
    }
    grid.hidden = false;
    state.hidden = true;
    var bulkBar = "";
    if (S.cat === "wishlist" && list.length > 0) {
      var inStock = list.filter(function (p) { return p.stock !== 0; });
      bulkBar = '<div class="bulk-bar">' +
        '<button class="btn primary" data-action="wish-move-all" ' + (inStock.length ? "" : "disabled") + ">" +
        "Move all to cart (" + inStock.length + ")</button>" +
        '<button class="btn ghost" data-action="wish-clear">Clear wishlist</button></div>';
    }
    grid.innerHTML = bulkBar + list.map(cardHTML).join("");
  }

  /* ---------------- TON Connect (lazy-loaded) ---------------- */
  var TON_UI_URL = "https://unpkg.com/@tonconnect/ui@3.0.2/dist/tonconnect-ui.min.js";
  var TON_MANIFEST_URL = "https://cdn.jsdelivr.net/gh/Pr3eve6ti2o/nova-shop-assets/tonconnect/tonconnect-manifest.json";
  var TON_MERCHANT = ""; // set from catalog.json (merchant_ton_address)
  var tonUI = null;
  var tonLoading = false;

  function loadTonConnect() {
    return new Promise(function (resolve, reject) {
      if (window.TON_CONNECT_UI) return resolve(window.TON_CONNECT_UI);
      var s = document.createElement("script");
      s.src = TON_UI_URL;
      s.onload = function () { resolve(window.TON_CONNECT_UI); };
      s.onerror = function () { reject(new Error("Failed to load TON Connect")); };
      document.head.appendChild(s);
    });
  }
  async function ensureTonUI() {
    var NS = await loadTonConnect();
    if (!tonUI) {
      tonUI = new NS.TonConnectUI({
        manifestUrl: TON_MANIFEST_URL,
        actionsConfiguration: {
          twaReturnUrl: "https://t.me/testssscbot/novashop"
        }
      });
      try { await tonUI.connectionRestored; } catch (e) {}
      tonUI.onStatusChange(function () { syncTonButton(); });
    }
    return tonUI;
  }
  function syncTonButton() {
    var btn = $("ton-pay-btn");
    if (!btn) return;
    var hasItems = Object.keys(S.cart).some(function (id) { return S.byId[id]; });
    btn.hidden = !(IN_TG && hasItems && TON_MERCHANT);
    // D3: update the label span instead of replacing innerHTML (preserves SVG).
    var label = $("ton-pay-label");
    if (label) label.textContent = (tonUI && tonUI.wallet) ? "Pay with TON · connected" : "Pay with TON";
  }
  async function payWithTon() {
    if (S.actionLoading || tonLoading) return;
    var ids = Object.keys(S.cart).filter(function (id) { return S.byId[id]; });
    if (!ids.length || !TON_MERCHANT) return;
    tonLoading = true;
    syncTonButton();
    try {
      var ui = await ensureTonUI();
      if (!ui.wallet) {
        ui.openModal();
        tonLoading = false;
        syncTonButton();
        return;
      }
      // Convert USD total to nanotons (1 TON = 1e9 nanotons).
      // Uses the same rate logic as the bot; bot re-validates server-side.
      var usdTotal = cartSubtotal() / 100;
      var tonRate = await fetchTonRate(); // USD per TON
      if (!tonRate) throw new Error("Rate unavailable");
      var nanoAmount = String(Math.round((usdTotal / tonRate) * 1e9));
      var tx = {
        validUntil: Math.floor(Date.now() / 1000) + 300,
        network: "-239",
        messages: [{ address: TON_MERCHANT, amount: nanoAmount }]
      };
      var result = await ui.sendTransaction(tx);
      // M3: wallet.account.address is raw; toncenter returns user-friendly
      // (UQ…/EQ…) form, which the bot matches against. Convert first.
      var sender = ui.wallet.account.address;
      try {
        if (ui.toUserFriendlyAddress) sender = ui.toUserFriendlyAddress(sender);
        else if (window.TonConnectUI && window.TonConnectUI.toUserFriendlyAddress) {
          sender = window.TonConnectUI.toUserFriendlyAddress(sender);
        }
      } catch (e) { /* keep raw as fallback */ }
      // Notify the bot; it verifies via toncenter and fulfills the order.
      var items = ids.map(function (id) { return { id: Number(id), qty: S.cart[id] }; });
      tg.sendData(JSON.stringify({
        type: "tonconnect_paid",
        boc: result.boc,
        sender: sender,
        amount_nano: nanoAmount,
        items: items,
        promo: S.promo || ""
      }));
      toast("Payment submitted. Confirming on-chain…", "info");
    } catch (e) {
      var msg = String((e && e.message) || "");
      if (/reject|cancel/i.test(msg)) toast("Payment cancelled.", "info");
      else toast("TON payment failed. Try again or use another method.", "error");
    }
    tonLoading = false;
    syncTonButton();
  }
  async function fetchTonRate() {
    try {
      var r = await fetch("https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd");
      var j = await r.json();
      return j["the-open-network"] && j["the-open-network"].usd;
    } catch (e) { return 0; }
  }

  /* ---------------- render: cart ---------------- */
  function stepperHTML(id, qty, p, allowZero) {
    var max = maxQty(p);
    var decDisabled = allowZero ? (qty < 1) : (qty <= 1);
    return '<div class="stepper" role="group" aria-label="Quantity for ' + esc(p.name) + '">' +
      '<button class="step-btn" data-action="dec" data-id="' + id + '" aria-label="Decrease quantity" ' +
        (decDisabled ? "disabled" : "") + ">" + icon("minus") + "</button>" +
      '<span class="step-val" aria-live="polite" aria-atomic="true">' + qty + "</span>" +
      '<button class="step-btn" data-action="inc" data-id="' + id + '" aria-label="Increase quantity" ' +
        (qty >= max ? "disabled" : "") + ">" + icon("plus") + "</button></div>";
  }

  function renderCart() {
    var ids = Object.keys(S.cart).filter(function (id) { return S.byId[id]; });
    var empty = ids.length === 0;
    $("cart-empty").hidden = !empty;
    $("cart-body").hidden = empty;
    if (empty) {
      var best = bestsellers();
      $("best-wrap").hidden = best.length === 0;
      if (best.length > 0) $("best-rail").innerHTML = best.map(railCardHTML).join("");
      return;
    }

    var rows = ids.map(function (id) {
      var p = S.byId[id], qty = S.cart[id];
      return '<div class="cart-row">' + visualHTML(p, "sm", { badges: false }) +
        '<div class="cart-info"><div class="cart-name">' + esc(p.name) + "</div>" +
          '<div class="cart-unit">' + money(p.price_cents) + " each</div></div>" +
        '<div class="cart-side"><div class="cart-line">' + money(p.price_cents * qty) + "</div>" +
          stepperHTML(id, qty, p, true) +
          '<button class="cart-remove" data-action="rm" data-id="' + id +
            '" aria-label="Remove ' + esc(p.name) + ' from cart">Remove</button></div></div>';
    }).join("");
    $("cart-items").innerHTML = rows;

    // promo: collapsed behind a toggle (Baymard); applied state replaces both
    var hasPromo = !!S.promo;
    $("promo-applied").hidden = !hasPromo;
    $("promo-collapsed").hidden = hasPromo;
    if (hasPromo) {
      $("promo-tag").textContent = S.promo;
    } else {
      $("promo-form").hidden = !S.promoOpen;
      $("promo-toggle").setAttribute("aria-expanded", S.promoOpen ? "true" : "false");
    }

    // summary: Subtotal and Total are ALWAYS visible; Discount only with a promo
    var sub = cartSubtotal();
    $("sum-subtotal").textContent = money(sub);
    $("sum-promo-row").hidden = !hasPromo;
    $("sum-total").textContent = money(sub);
    syncTonButton();
  }

  /* ---------------- render: sheets ---------------- */
  function reviewsHTML(p) {
    var html = '<div class="reviews-wrap"><h2 class="section-title">Reviews</h2>';
    if (p.reviews > 0) {
      html += '<div class="reviews-summary"><span class="reviews-big">' + p.rating.toFixed(1) + "</span>" +
        '<div><div class="stars">' + starsHTML(p.rating) + "</div>" +
        "<small>" + p.reviews + (p.reviews === 1 ? " verified review" : " verified reviews") + "</small></div></div>";
      // Individual reviews come from the catalog export when available
      if (p.review_list && p.review_list.length) {
        html += p.review_list.slice(0, 3).map(function (r) {
          return '<div class="review"><div class="review-head"><b>' + esc(r.author || "Verified buyer") + "</b>" +
            '<span class="stars sm">' + starsHTML(r.rating || 5) + "</span></div>" +
            (r.text ? "<p>" + esc(r.text) + "</p>" : "") + "</div>";
        }).join("");
      }
    } else {
      html += '<p class="reviews-empty">No reviews yet. Only verified buyers can review — bought this? Share your experience in the bot after delivery.</p>';
    }
    return html + "</div>";
  }
  function starsHTML(rating) {
    var full = Math.round(rating);
    var out = "";
    for (var i = 1; i <= 5; i++) {
      out += '<span class="star' + (i <= full ? " on" : "") + '" aria-hidden="true">★</span>';
    }
    return out;
  }

  function specsHTML(p) {
    var rows = [];
    rows.push(["Type", isDigital(p) ? "Digital product" : "Physical product"]);
    rows.push(["Category", catName(p.category_id) || "General"]);
    if (p.reviews > 0) rows.push(["Rating", p.rating.toFixed(1) + " / 5 (" + p.reviews + " reviews)"]);
    if (p.stock === -1) rows.push(["Delivery", "Instant digital delivery"]);
    else if (p.stock === 0) rows.push(["Availability", "Out of stock"]);
    else rows.push(["Availability", p.stock <= 5 ? "Only " + p.stock + " left" : "In stock"]);
    var html = '<div class="specs-wrap"><h2 class="section-title">Specifications</h2><dl class="specs">';
    rows.forEach(function (r) {
      html += "<dt>" + esc(r[0]) + "</dt><dd>" + esc(r[1]) + "</dd>";
    });
    return html + "</dl></div>";
  }
  function faqHTML(p) {
    var faqs = [
      ["How fast is delivery?",
       isDigital(p) ? "Digital products are delivered instantly after payment confirmation."
                    : "Physical orders ship within 24 hours."],
      ["What payment methods do you accept?",
       "Telegram Stars, USDT (ERC-20/TRC-20), TON, and BTC. Card payments coming soon."],
      ["What is your refund policy?",
       "See our Refund Policy in the store footer. Digital goods and on-chain crypto payments have specific terms."]
    ];
    var html = '<div class="faq-wrap"><h2 class="section-title">Common questions</h2>';
    faqs.forEach(function (f, i) {
      html += '<button class="faq-q" data-action="faq-tog" data-id="' + p.id + "-" + i + '" aria-expanded="false">' +
        "<span>" + esc(f[0]) + "</span>" + icon("chevron") + "</button>" +
        '<div class="faq-a" id="faq-' + p.id + "-" + i + '" hidden><p>' + esc(f[1]) + "</p></div>";
    });
    return html + "</div>";
  }

  function sheetProductHTML(p) {
    var sm = stockMeta(p);
    var oos = p.stock === 0;
    var off = offPct(p);
    var old = off > 0 ? '<s class="old">' + money(p.old_price_cents) + "</s>" : "";
    var offTag = off > 0 ? '<span class="off-badge" style="position:static">-' + off + "%</span>" : "";
    var rating = p.reviews > 0
      ? '<span class="rating">' + icon("star", "ic-xs") + "<b>" + p.rating.toFixed(1) + "</b>" +
        "<span>&nbsp;·&nbsp;" + p.reviews + (p.reviews === 1 ? " review" : " reviews") + "</span></span>"
      : '<span class="rating new">New arrival</span>';
    var deliv = isDigital(p)
      ? '<div class="deliv-line">' + icon("zap") + "<span>Digital delivery · instant</span></div>"
      : '<div class="deliv-line">' + icon("truck") + "<span>Ships in 24h</span></div>";
    var max = maxQty(p);
    var alertOn = !!(S.stockAlerts && S.stockAlerts[p.id]);
    var cta = oos
      ? '<button class="btn ' + (alertOn ? "primary" : "secondary") + ' btn-block btn-lg" data-action="notify-stock" data-id="' + p.id + '">' +
        icon("bell") + (alertOn ? " Alert set — tap to cancel" : " Notify me when back in stock") + "</button>"
      : '<div class="sheet-cta-row">' + stepperHTML("sheet", 1, p, false) +
        '<button class="btn primary btn-lg" id="sheet-add" data-action="sheet-add" data-id="' + p.id + '">' +
          '<span class="btn-label" id="sheet-add-label">Add to cart &middot; ' + money(p.price_cents) + "</span>" +
        "</button></div>" +
        '<button class="btn secondary btn-block" data-action="sheet-buy" data-id="' + p.id + '">Buy now</button>';
    var related = relatedProducts(p);
    var relHTML = related.length > 0
      ? '<div class="related-wrap"><h2 class="section-title">You may also like</h2>' +
        '<div class="rail">' + related.map(railCardHTML).join("") + "</div></div>"
      : "";
    return visualHTML(p, "lg") +
      '<nav class="crumbs" aria-label="Breadcrumb"><span>' + esc(catName(p.category_id) || "Store") + "</span>" +
        '<span aria-hidden="true">&rsaquo;</span><span class="crumb-cur">' + esc(p.name) + "</span></nav>" +
      '<h3 class="sheet-title">' + esc(p.name) + "</h3>" +
      '<div class="sheet-actions"><button class="icon-btn" data-action="share" data-id="' + p.id + '"' +
        ' aria-label="Share ' + esc(p.name) + '">' + icon("share") + "</button>" +
        '<button class="icon-btn' + (S.wish[p.id] ? " is-wished" : "") + '" data-action="wish" data-id="' + p.id + '"' +
        ' aria-label="' + (S.wish[p.id] ? "Remove from" : "Save to") + ' wishlist" aria-pressed="' + !!S.wish[p.id] + '">' +
        icon("heart") + "</button></div>" +
      '<div class="sheet-rating">' + rating +
        '<span class="stock s-' + sm.tone + '">' + esc(sm.label) + "</span></div>" +
      '<div class="sheet-price-row"><span class="sheet-price" id="sheet-price">' + money(p.price_cents) + "</span>" + old + offTag + "</div>" +
      deliv +
      (p.description ? '<p class="sheet-desc">' + esc(p.description) + "</p>" : "") +
      cta +
      trustRowHTML(p) +
      bundleHTML(p) +
      specsHTML(p) +
      reviewsHTML(p) +
      faqHTML(p) +
      relHTML;
  }

  function sortSheetHTML() {
    var out = '<h3 class="sheet-title">Sort by</h3><div role="radiogroup" aria-label="Sort products">';
    SORTS.forEach(function (s) {
      var on = S.sort === s.id;
      out += '<button class="sort-opt' + (on ? " is-on" : "") + '" data-action="sort-set" data-id="' + s.id +
        '" role="radio" aria-checked="' + on + '">' +
        '<span class="radio" aria-hidden="true"></span><span>' + esc(s.label) + "</span></button>";
    });
    return out + "</div>";
  }

  function policyHTML(key) {
    var pol = (window.NOVA_POLICIES || {})[key];
    if (!pol) return '<h3 class="sheet-title">Not available</h3><p>This policy is not available right now.</p>';
    return '<div class="policy-body"><h3 class="sheet-title">' + esc(pol.title) + "</h3>" +
      '<div class="policy-text">' + esc(pol.body) + "</div>" +
      '<div class="policy-actions"><button class="btn secondary btn-block" data-action="close-sheet">Close</button></div></div>';
  }

  function supportHTML() {
    return '<div class="policy-body"><h3 class="sheet-title">Support</h3>' +
      '<div class="policy-text">Need help with an order, a payment, or a product question?\n\n' +
      "Our team replies within ~2 hours, 08:00\u201320:00 IST.\n\n" +
      "The fastest way to reach us is right in the bot chat \u2014 tap the button below to open it.</div>" +
      '<div class="policy-actions">' +
      '<button class="btn primary btn-block" data-action="open-bot">Chat with support</button>' +
      '<button class="btn secondary btn-block" data-action="close-sheet">Close</button></div></div>';
  }

  function trustRowHTML(p) {
    var digital = isDigital(p);
    return '<div class="trust-row multi">' +
      '<div class="trust-item">' + icon("shield") +
        "<span>Secure checkout <small>\u00b7 encrypted &amp; verified</small></span></div>" +
      '<div class="trust-item">' + icon("refresh") +
        "<span>Money-back guarantee <small>\u00b7 7-day DOA cover</small></span></div>" +
      '<div class="trust-item">' + icon(digital ? "zap" : "truck") +
        (digital ? "<span>Instant delivery <small>\u00b7 right after payment</small></span>"
                 : "<span>Ships in 24h <small>\u00b7 tracked delivery</small></span>") +
      "</div></div>";
  }

  function syncFilterBadge() {
    var n = activeFilterCount();
    var badge = $("filter-count");
    var btn = $("filter-btn");
    if (badge) badge.hidden = n === 0;
    if (badge) badge.textContent = n;
    if (btn) btn.classList.toggle("is-active", n > 0);
  }

  function filterSheetHTML() {
    var f = S.filters;
    var maxCents = 0;
    S.products.forEach(function (p) { maxCents = Math.max(maxCents, Number(p.price_cents) || 0); });
    var cap = f.maxPrice > 0 ? f.maxPrice : maxCents;
    function tog(key, label, hint) {
      var on = !!f[key];
      return '<button class="filter-tog' + (on ? " is-on" : "") + '" data-action="filter-tog" data-id="' + key + '"' +
        ' role="switch" aria-checked="' + on + '">' +
        '<span class="radio" aria-hidden="true"></span><span><b>' + esc(label) + "</b>" +
        (hint ? '<br><small>' + esc(hint) + "</small>" : "") + "</span></button>";
    }
    return '<h3 class="sheet-title">Filters</h3>' +
      '<div class="filter-group"><div class="filter-label">Max price: <b id="filter-price-label">' + money(cap) + "</b></div>" +
        '<input type="range" id="filter-price" class="filter-range" min="0" max="' + maxCents + '" step="100" value="' + cap + '"' +
        ' aria-label="Maximum price"></div>' +
      '<div class="filter-group">' +
        tog("inStock", "In stock only", "Hide sold-out items") +
        tog("onSale", "On sale", "Discounted items only") +
      "</div>" +
      '<div class="filter-group"><div class="filter-label">Minimum rating</div><div class="filter-stars">' +
        [0, 3, 4, 4.5].map(function (r) {
          var on = f.minRating === r;
          var label = r === 0 ? "Any" : r + "+ stars";
          return '<button class="chip' + (on ? " is-on" : "") + '" data-action="filter-rating" data-id="' + r + '">' + label + "</button>";
        }).join("") + "</div></div>" +
      '<div class="filter-actions">' +
        '<button class="btn ghost btn-block" data-action="filter-clear">Clear all</button>' +
        '<button class="btn primary btn-block" data-action="filter-apply">Show results</button>' +
      "</div>";
  }

  function referralSheetHTML() {
    return '<h3 class="sheet-title">Refer &amp; Earn</h3>' +
      '<div class="referral-hero"><span class="referral-emoji">🎁</span>' +
      "<p>Share Nova Shop with friends. When they make their first purchase, " +
      "you both get rewarded.</p></div>" +
      '<button class="btn primary btn-block btn-lg" data-action="referral-get">' +
      "Get my referral link</button>" +
      '<p class="hint-text" style="text-align:center;margin-top:var(--sp-2)">Your personal link will be sent in the bot chat.</p>';
  }
  function ordersSheetHTML() {
    return '<h3 class="sheet-title">My Orders</h3>' +
      '<p class="hint-text">Your recent orders will be sent to the bot chat.</p>' +
      '<button class="btn primary btn-block btn-lg" data-action="orders-get">' +
      "View my orders</button>";
  }

  function renderSheet() {
    if (!S.sheet) return;
    var body = $("sheet-body");
    if (S.sheet.mode === "product") {
      var p = S.byId[S.sheet.id];
      if (!p) { closeSheet(); return; }
      body.innerHTML = sheetProductHTML(p);
    } else if (S.sheet.mode === "sort") {
      body.innerHTML = sortSheetHTML();
    } else if (S.sheet.mode === "filter") {
      body.innerHTML = filterSheetHTML();
      var rng = $("filter-price");
      if (rng) rng.addEventListener("input", function () {
        $("filter-price-label").textContent = money(Number(rng.value));
      });
    } else if (S.sheet.mode === "referral") {
      body.innerHTML = referralSheetHTML();
    } else if (S.sheet.mode === "orders") {
      body.innerHTML = ordersSheetHTML();
    } else if (S.sheet.mode === "policy") {
      body.innerHTML = S.sheet.id === "support" ? supportHTML() : policyHTML(S.sheet.id);
    }
    $("sheet-inner").scrollTop = 0;
  }

  function setClosingConfirmation(on) {
    if (!tg || !atLeast("6.2")) return;
    try {
      if (on && typeof tg.enableClosingConfirmation === "function") tg.enableClosingConfirmation();
      else if (!on && typeof tg.disableClosingConfirmation === "function") tg.disableClosingConfirmation();
    } catch (e) {}
  }

  var sheetHideTimer = null;
  function openSheet(mode, id) {
    // M1: cancel any pending hide from a recent closeSheet() — otherwise the
    // stale timeout hides this newly opened sheet.
    if (sheetHideTimer) { clearTimeout(sheetHideTimer); sheetHideTimer = null; }
    if (mode === "product") {
      if (!S.byId[id]) return;
      pushRecent(id);
    }
    S.sheet = { mode: mode, id: id, qty: 1 };
    S.lastFocus = document.activeElement;
    renderSheet();
    $("scrim").hidden = false;
    $("sheet").hidden = false;
    document.body.classList.add("no-scroll");
    requestAnimationFrame(function () { requestAnimationFrame(function () {
      $("sheet").classList.add("open");
    }); });
    setTimeout(function () { $("sheet-close").focus(); }, 80);
    buzz("light");
    syncChrome();
  }

  function closeSheet() {
    if (!S.sheet) return;
    S.sheet = null;
    setClosingConfirmation(false);
    $("sheet").classList.remove("open");
    sheetHideTimer = setTimeout(function () {
      sheetHideTimer = null;
      $("sheet").hidden = true;
      $("scrim").hidden = true;
      document.body.classList.remove("no-scroll");
    }, 260);
    if (S.lastFocus && S.lastFocus.focus) { try { S.lastFocus.focus(); } catch (e) {} }
    syncChrome();
  }

  /* ---------------- render: chrome (header, actionbar, TG buttons) ---------------- */
  function setActionLoading(on) {
    S.actionLoading = on;
    var btn = $("actionbar-btn");
    btn.classList.toggle("is-loading", on);
    btn.disabled = on;
    $("actionbar-spinner").hidden = !on;
    if (!tg || !tg.MainButton) return;
    try {
      if (on && typeof tg.MainButton.showProgress === "function") tg.MainButton.showProgress(false);
      else if (!on && typeof tg.MainButton.hideProgress === "function") tg.MainButton.hideProgress();
    } catch (e) {}
  }

  // What should the single primary action be right now?
  // Note: checkout hands off to the bot in one tap — the bot shows its own
  // Review & confirm screen, so there is no in-app confirm step (no double
  // confirmation).
  function primaryAction() {
    if (S.sheet) return null;
    if (S.view === "home" && cartCount() > 0)
      return { kind: "goto-cart", label: "View cart \u00b7 " + money(cartSubtotal()) };
    if (S.view === "cart" && cartCount() > 0)
      return { kind: "confirm", label: "Checkout \u00b7 " + money(cartSubtotal()) };
    return null;
  }

  function runPrimaryAction() {
    var a = primaryAction();
    if (!a) return;
    if (a.kind === "goto-cart") goView("cart");
    else if (a.kind === "confirm") doCheckout();
  }

  function syncChrome() {
    var n = cartCount();

    // header
    $("brand-name").textContent = S.view === "cart" ? "Your cart" : "Nova Shop";
    $("nav-back").hidden = S.view === "home";
    $("cart-btn").hidden = S.view !== "home";
    var badge = $("cart-badge");
    badge.hidden = n === 0;
    badge.textContent = n > 99 ? "99+" : String(n);

    // sticky in-page action bar (same bar, same alignment, on home and cart)
    var a = primaryAction();
    var showBar = !!a;
    $("actionbar").hidden = !showBar;
    document.body.classList.toggle("has-actionbar", showBar);
    if (showBar) {
      $("actionbar-label").textContent = a.label;
    }

    if (!tg) return;
    // Telegram MainButton mirrors the primary action
    try {
      var mb = tg.MainButton;
      if (a) {
        mb.setText(a.label);
        if (!mb.isVisible) mb.show();
      } else if (mb.isVisible) {
        mb.hide();
      }
      // Telegram BackButton follows the view stack
      var bb = tg.BackButton;
      if (S.sheet || S.view !== "home") { if (!bb.isVisible) bb.show(); }
      else if (bb.isVisible) { bb.hide(); }
    } catch (e) {}
  }

  function render() {
    $("view-home").hidden = S.view !== "home";
    $("view-cart").hidden = S.view !== "cart";
    $("view-success").hidden = S.view !== "success";
    if (S.view === "home") { renderHome(); syncFilterBadge(); }
    if (S.view === "cart") renderCart();
    syncChrome();
  }

  function goView(v) {
    S.view = v;
    window.scrollTo(0, 0);
    buzz("light");
    render();
  }

  /* ---------------- actions ---------------- */
  function addToCart(id, qty, silent) {
    var p = S.byId[id];
    if (!p || p.stock === 0) return;
    var cur = S.cart[id] || 0;
    var nq = Math.min(maxQty(p), cur + qty);
    if (nq <= 0) return;
    var capped = nq < cur + qty;
    S.cart[id] = nq;
    saveCart();
    buzz("light");
    render();
    if (!silent) toast(capped ? "Only " + maxQty(p) + " available \u2014 cart updated." : "Added to cart.", capped ? "info" : "success");
  }

  function setQty(id, qty) {
    var p = S.byId[id];
    if (!p || qty <= 0) return;
    var nq = Math.min(maxQty(p), Math.max(1, qty));
    if (nq !== S.cart[id]) {
      S.cart[id] = nq;
      saveCart();
      buzz("light");
    }
    render();
  }

  function removeFromCart(id) {
    var p = S.byId[id];
    var qty = S.cart[id];
    if (!p || !qty) return;
    delete S.cart[id];
    saveCart();
    buzz("light");
    render();
    toast("Removed from cart.", "info", { action: {
      label: "Undo",
      fn: function () {
        var cur = S.cart[id] || 0;
        var nq = Math.min(maxQty(p), cur + qty);
        if (nq > 0) {
          S.cart[id] = nq;
          saveCart();
          buzz("light");
          render();
          toast("Restored to cart.", "success");
        }
      }
    } });
  }

  function applyPromo() {
    var v = ($("promo-input").value || "").trim().toUpperCase().slice(0, 32);
    if (!v) { toast("Enter a promo code first.", "info"); return; }
    S.promo = v;
    S.promoOpen = false;
    saveCart();
    chirp("success");
    toast("Promo code applied.", "success");
    render();
  }

  function updateSheetQty(d) {
    if (!S.sheet || S.sheet.mode !== "product") return;
    var p = S.byId[S.sheet.id];
    if (!p) return;
    var nq = Math.min(maxQty(p), Math.max(1, S.sheet.qty + d));
    if (nq === S.sheet.qty) return;
    S.sheet.qty = nq;
    buzz("light");
    var val = document.querySelector('#sheet-body .step-val');
    if (val) val.textContent = nq;
    var label = $("sheet-add-label");
    if (label) label.textContent = "Add to cart · " + money(p.price_cents * nq);
    var btns = document.querySelectorAll('#sheet-body .step-btn');
    if (btns.length === 2) {
      btns[0].disabled = nq <= 1;
      btns[1].disabled = nq >= maxQty(p);
    }
  }

  function doCheckout() {
    if (S.actionLoading) return;
    var ids = Object.keys(S.cart).filter(function (id) { return S.byId[id]; });
    if (ids.length === 0) return;
    if (!IN_TG || !tg.sendData) {
      toast("Checkout is only available inside Telegram. Open this store from the Telegram app to check out.", "error");
      return;
    }
    var items = ids.map(function (id) { return { id: Number(id), qty: S.cart[id] }; });
    var payloadObj = { items: items, promo: S.promo || "" };
    // Piggyback queued stock-alert syncs (C3: sendData closes the app, so this
    // is the only safe moment to sync them to the bot).
    if (S.pendingAlertSync && Object.keys(S.pendingAlertSync).length) {
      payloadObj.alert_sync = S.pendingAlertSync;
    }
    var payload = JSON.stringify(payloadObj);
    if (payload.length > SENDDATA_LIMIT) {
      toast("Your cart is too large to send. Remove some items and try again.", "error");
      return;
    }
    setActionLoading(true);
    buzz("medium");
    // C4: clear the cart BEFORE sendData — sendData closes the Mini App, so
    // anything after it never runs. Persist empty cart first.
    S.cart = {};
    S.promo = "";
    S.promoOpen = false;
    saveCart();
    S.pendingAlertSync = {};
    if (tgCloud) {
      try { tgCloud.setItem(ALERT_SYNC_KEY, "{}", function () {}); } catch (e) {}
    }
    var ok = false;
    try { tg.sendData(payload); ok = true; } catch (e) { ok = false; }
    if (!ok) {
      // sendData failed: restore the cart so nothing is lost.
      ids.forEach(function (id) {
        var it = items.filter(function (x) { return String(x.id) === String(id); })[0];
        if (it) S.cart[id] = it.qty;
      });
      saveCart();
      setActionLoading(false);
      toast("Couldn't send your order. Check your connection and try again.", "error");
      chirp("error");
      return;
    }
    // NOTE: the app closes here; the success screen is shown by the bot.
    setActionLoading(false);
  }

  /* ---------------- event delegation ---------------- */
  function onAction(a, t) {
    var id = t.getAttribute("data-id");
    switch (a) {
      case "open": openSheet("product", id); break;
      case "add": addToCart(id, 1); break;
      case "wish": toggleWish(id); break;
      case "ton-pay": payWithTon(); break;
      case "referral": openSheet("referral"); break;
      case "orders": openSheet("orders"); break;
      case "orders-get":
        // M5: sendData closes the app, so the toast must show BEFORE sending.
        // Brief delay lets the user read it, then the app closes into the chat.
        try {
          if (IN_TG && tg.sendData) {
            toast("Opening bot chat with your orders…", "success");
            setTimeout(function () {
              try { tg.sendData(JSON.stringify({ type: "get_orders" })); } catch (e) {}
            }, 700);
          } else {
            toast("Open the store from Telegram to view orders.", "info");
          }
        } catch (e) {
          toast("Couldn't request orders.", "error");
        }
        break;
      case "referral-get":
        try {
          if (IN_TG && tg.sendData) {
            toast("Opening bot chat with your referral link…", "success");
            setTimeout(function () {
              try { tg.sendData(JSON.stringify({ type: "get_referral" })); } catch (e) {}
            }, 700);
          } else {
            toast("Open the store from Telegram to get your referral link.", "info");
          }
        } catch (e) {
          toast("Couldn't request referral link.", "error");
        }
        break;
      case "notify-stock": toggleStockAlert(id); break;
      case "wish-move-all":
        (function () {
          var moved = 0;
          Object.keys(S.wish).forEach(function (pid) {
            var p = S.byId[pid];
            if (p && p.stock !== 0) {
              var cur = S.cart[pid] || 0;
              var max = maxQty(p);
              if (cur < max) { S.cart[pid] = cur + 1; moved++; }
              delete S.wish[pid];
            }
          });
          saveCart(); saveWish();
          toast(moved ? "Moved " + moved + " to cart." : "Nothing to move.", moved ? "success" : "info");
          buzz("medium");
          render();
        })();
        break;
      case "bundle-add":
        (function () {
          var parts = (id || "").split("|");
          var added = 0;
          parts.forEach(function (pid) {
            var bp = S.byId[pid];
            if (bp && bp.stock !== 0) {
              var cur = S.cart[pid] || 0;
              if (cur < maxQty(bp)) { S.cart[pid] = cur + 1; added++; }
            }
          });
          saveCart();
          toast(added === 2 ? "Bundle added to cart." : "Added what's available.", added ? "success" : "info");
          buzz("medium");
          render();
        })();
        break;
      case "wish-clear":
        S.wish = {};
        saveWish();
        toast("Wishlist cleared.", "info");
        render();
        break;
      case "faq-tog":
        (function () {
          var ans = $("faq-" + id);
          var btn = document.querySelector('[data-action="faq-tog"][data-id="' + id + '"]');
          if (!ans) return;
          var open = ans.hidden;
          ans.hidden = !open;
          if (btn) btn.setAttribute("aria-expanded", open);
          if (btn) btn.classList.toggle("is-open", open);
        })();
        break;
      case "suggest-product": openSheet("product", id); break;
      case "suggest-term":
        $("search").value = id;
        S.query = id;
        $("search-clear").hidden = false;
        $("search-suggest").hidden = true;
        render();
        break;
      case "suggest-cat":
        S.cat = id;
        S.query = "";
        $("search").value = "";
        $("search-clear").hidden = true;
        $("search-suggest").hidden = true;
        render();
        break;
      case "share":
        (function () {
          var sp = S.byId[id];
          if (!sp) return;
          var url = "https://t.me/testssscbot?startapp=p_" + sp.id;
          var text = sp.name + " — " + money(sp.price_cents) + " at Nova Shop";
          function fallback() {
            var done = false;
            try {
              if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text + "\n" + url).then(function () { done = true; });
              }
            } catch (e) {}
            setTimeout(function () {
              toast(done ? "Link copied to clipboard." : "Copy this link: " + url, done ? "success" : "info");
            }, 100);
          }
          try {
            if (navigator.share) {
              navigator.share({ title: "Nova Shop", text: text, url: url }).catch(function () {});
            } else fallback();
          } catch (e) { fallback(); }
          buzz("light");
        })();
        break;
      case "inc":
        if (id === "sheet") updateSheetQty(1);
        else setQty(id, (S.cart[id] || 0) + 1);
        break;
      case "dec":
        if (id === "sheet") updateSheetQty(-1);
        else if ((S.cart[id] || 0) <= 1) removeFromCart(id);
        else setQty(id, (S.cart[id] || 0) - 1);
        break;
      case "rm": removeFromCart(id); break;
      case "chip":
        S.cat = t.getAttribute("data-cat");
        buzz("light");
        render();
        break;
      case "open-sort": openSheet("sort"); break;
      case "open-filter": openSheet("filter"); break;
      case "filter-tog":
        S.filters[id] = !S.filters[id];
        renderSheet();
        break;
      case "filter-rating":
        S.filters.minRating = Number(id);
        renderSheet();
        break;
      case "filter-clear":
        S.filters = { maxPrice: 0, inStock: false, onSale: false, minRating: 0 };
        closeSheet();
        syncFilterBadge();
        render();
        break;
      case "filter-apply":
        var rng = $("filter-price");
        var maxCents = 0;
        S.products.forEach(function (p) { maxCents = Math.max(maxCents, Number(p.price_cents) || 0); });
        S.filters.maxPrice = (rng && Number(rng.value) < maxCents) ? Number(rng.value) : 0;
        closeSheet();
        syncFilterBadge();
        render();
        toast(activeFilterCount() ? "Filters applied." : "Filters cleared.", "info");
        break;
      case "sort-set":
        S.sort = t.getAttribute("data-id") || "featured";
        buzz("light");
        closeSheet();
        render();
        break;
      case "toggle-promo":
        S.promoOpen = !S.promoOpen;
        $("promo-form").hidden = !S.promoOpen;
        t.setAttribute("aria-expanded", S.promoOpen ? "true" : "false");
        if (S.promoOpen) { var pi = $("promo-input"); if (pi) pi.focus(); }
        buzz("light");
        break;
      case "sheet-add":
        addToCart(id, S.sheet ? S.sheet.qty : 1);
        closeSheet();
        break;
      case "sheet-buy":
        addToCart(id, S.sheet ? S.sheet.qty : 1, true);
        closeSheet();
        goView("cart");
        break;
      case "apply-promo": applyPromo(); break;
      case "remove-promo":
        S.promo = "";
        S.promoOpen = false;
        saveCart();
        toast("Promo code removed.", "info");
        render();
        break;
      case "goto-cart": goView("cart"); break;
      case "goto-home": goView("home"); break;
      case "confirm": doCheckout(); break;
      case "close-sheet": closeSheet(); break;
      case "policy": openSheet("policy", id); break;
      case "support": openSheet("policy", "support"); break;
      case "open-bot":
        // The Mini App was opened from the bot chat — closing it drops the
        // user right back into the conversation with support.
        closeSheet();
        if (tg && tg.close) { try { tg.close(); } catch (e) {} }
        else { toast("Open the bot chat to message support.", "info"); }
        break;
      case "dismiss-notice": $("web-notice").hidden = true; break;
      case "retry": fetchCatalog(); break;
      case "clear-search":
        S.query = "";
        $("search").value = "";
        $("search-clear").hidden = true;
        render();
        break;
      case "chip-all":
        S.cat = "all";
        S.query = "";
        var si = $("search");
        if (si) si.value = "";
        $("search-clear").hidden = true;
        S.filters = { maxPrice: 0, inStock: false, onSale: false, minRating: 0 };
        syncFilterBadge();
        render();
        break;
    }
  }

  function bindEvents() {
    document.addEventListener("click", function (e) {
      // sticky action bar button has no data-action; handle by id
      var barBtn = e.target.closest && e.target.closest("#actionbar-btn");
      if (barBtn) { runPrimaryAction(); return; }
      // scrim click closes the sheet
      if (e.target && e.target.id === "scrim") { closeSheet(); return; }
      var t = e.target.closest ? e.target.closest("[data-action]") : null;
      if (!t) return;
      onAction(t.getAttribute("data-action"), t);
    });

    // keyboard: open cards with Enter/Space, Escape closes sheet
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        if (S.sheet) { closeSheet(); return; }
        var si = $("search");
        if (document.activeElement === si && si.value) {
          si.value = ""; S.query = ""; $("search-clear").hidden = true; render();
        }
        return;
      }
      if ((e.key === "Enter" || e.key === " ") && e.target &&
          e.target.matches && e.target.matches('.card[data-action="open"]')) {
        e.preventDefault();
        openSheet("product", e.target.getAttribute("data-id"));
      }
    });

    // live search + suggestions (M6/D7: debounced to avoid full re-render jank
    // on every keystroke with a large catalog).
    var search = $("search");
    var searchTimer = null;
    search.addEventListener("input", function () {
      S.query = search.value;
      $("search-clear").hidden = !search.value;
      renderSuggest();
      if (searchTimer) clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        searchTimer = null;
        if (S.view === "home") renderHome();
        syncChrome();
      }, 150);
    });
    search.addEventListener("focus", function () { renderSuggest(); });
    search.addEventListener("blur", function () {
      // delay so suggestion taps register before hiding
      setTimeout(function () { $("search-suggest").hidden = true; }, 150);
    });
    search.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && search.value.trim()) {
        pushRecentSearch(search.value.trim());
        $("search-suggest").hidden = true;
        search.blur();
      }
    });
    $("search-clear").addEventListener("click", function () {
      search.value = ""; S.query = "";
      $("search-clear").hidden = true;
      search.focus();
      render();
    });
    // nav back (mirrors Telegram BackButton)
    $("nav-back").addEventListener("click", function () {
      if (S.sheet) closeSheet();
      else if (S.view !== "home") goView("home");
    });

    // sheet swipe-down-to-close on the handle
    var handle = $("sheet-handle"), inner = $("sheet-inner");
    var startY = null;
    handle.addEventListener("touchstart", function (e) {
      startY = e.touches[0].clientY;
    }, { passive: true });
    handle.addEventListener("touchmove", function (e) {
      if (startY === null) return;
      var dy = e.touches[0].clientY - startY;
      if (dy > 0) inner.style.transform = "translateY(" + dy + "px)";
    }, { passive: true });
    handle.addEventListener("touchend", function (e) {
      if (startY === null) return;
      var dy = (e.changedTouches[0] || {}).clientY - startY;
      startY = null;
      inner.style.transform = "";
      if (dy > 90) closeSheet();
    });
  }

  /* ---------------- telegram wiring ---------------- */
  function setupTelegram() {
    if (!IN_TG) {
      // Outside-Telegram notice (QA: this MUST render) — dismissible.
      $("web-notice").hidden = false;
      document.documentElement.setAttribute("data-scheme",
        (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light");
      return;
    }
    try {
      tg.ready();
      tg.expand();
      if (typeof tg.disableVerticalSwipes === "function" && atLeast("7.7")) {
        try { tg.disableVerticalSwipes(); } catch (e) {}
      }
      document.documentElement.setAttribute("data-scheme", tg.colorScheme || "light");
      tg.onEvent("themeChanged", function () {
        document.documentElement.setAttribute("data-scheme", tg.colorScheme || "light");
      });
      tg.onEvent("mainButtonClicked", runPrimaryAction);
      tg.onEvent("backClicked", function () {
        if (S.sheet) closeSheet();
        else if (S.view !== "home") goView("home");
      });
    } catch (e) { /* stay functional without Telegram APIs */ }
  }

  /* ---------------- init ---------------- */
  function init() {
    loadCart();
    loadWish();
    loadSearches();
    if (tgCloud) {
      try {
        tgCloud.getItem(ALERT_KEY, function (err, raw) {
          if (err || !raw) return;
          var d = null;
          try { d = JSON.parse(raw); } catch (e) { return; }
          (d.ids || []).forEach(function (id) { S.stockAlerts[id] = true; });
        });
        tgCloud.getItem(ALERT_SYNC_KEY, function (err, raw) {
          if (err || !raw) return;
          try { S.pendingAlertSync = JSON.parse(raw) || {}; } catch (e) {}
        });
      } catch (e) {}
    }
    setupTelegram();
    bindEvents();
    fetchCatalog();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
