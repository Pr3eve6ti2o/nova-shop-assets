'use client'
import React, { useState } from 'react'

/**
 * Orders list header: create a manual order for a customer — Comp
 * (free) or charged to their store-credit balance. The bot creates
 * the order (catalogue prices only) via its internal API; the new
 * order is mirrored back into this list.
 */
export default function ManualOrderTools() {
  const [tgId, setTgId] = useState('')
  const [items, setItems] = useState('')
  const [kind, setKind] = useState('comp')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const create = async () => {
    const parsed = items
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .map((pair) => {
        const [productId, qty] = pair.split(':')
        return { productId: Number(productId), qty: Number(qty || 1) }
      })
    if (!tgId || !parsed.length || parsed.some((i) => !i.productId || !i.qty)) {
      setMsg('Fill in the Telegram user id and items like “7:2, 8:1”.')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const res = await fetch('/api/orders/create-manual', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tgUserId: Number(tgId), items: parsed, kind, note: note || undefined }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(json?.error || 'Create failed')
        return
      }
      setMsg(`Order ${json.orderNumber} created.`)
      window.location.reload()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', margin: '8px 0' }}>
      <input aria-label="Telegram user id" placeholder="Customer TG id" value={tgId}
        onChange={(e) => setTgId(e.target.value)} style={{ width: 130 }} />
      <input aria-label="Items as productId:qty" placeholder="Items: 7:2, 8:1" value={items}
        onChange={(e) => setItems(e.target.value)} style={{ width: 170 }} />
      <select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}>
        <option value="comp">Comp (free)</option>
        <option value="balance">Charge balance</option>
      </select>
      <input aria-label="Note (optional)" placeholder="Note" value={note}
        onChange={(e) => setNote(e.target.value)} style={{ width: 140 }} />
      <button type="button" onClick={create} disabled={busy}>Create order</button>
      {msg && <span>{msg}</span>}
    </div>
  )
}
