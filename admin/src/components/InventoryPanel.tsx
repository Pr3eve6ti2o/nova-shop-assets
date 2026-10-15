'use client'
import React, { useCallback, useEffect, useState } from 'react'
import { useDocumentInfo } from '@payloadcms/ui'

type Inventory = {
  id: number
  name: string
  kind: string
  is_active: boolean
  is_unlimited: boolean
  stock: number
  unused_values: number
}

/**
 * Live Inventory section on the Product detail (Medusa inventory
 * pattern, 2026-10-16): shows the BOT's live stock — not the Payload
 * catalogue copy — and restocks against it. Physical products take a
 * quantity (add to current stock, or set an absolute level); digital
 * products take pasted keys, one per line. Every restock needs a note
 * and lands in the bot's audit log via the internal API.
 */
export default function InventoryPanel() {
  const { id } = useDocumentInfo()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [inv, setInv] = useState<Inventory | null>(null)
  const [error, setError] = useState('')
  const [mode, setMode] = useState<'add' | 'set'>('add')
  const [qty, setQty] = useState('')
  const [values, setValues] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    if (!id) return
    try {
      const res = await fetch(`/api/products/${id}/inventory`)
      const json = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(json?.error || 'Failed to load live inventory')
        return
      }
      setInv(json.inventory)
      setError('')
    } catch {
      setError('Failed to load live inventory')
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const restock = async () => {
    if (!note.trim()) {
      setMsg('A note is required — it goes in the audit log.')
      return
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const body: Record<string, any> = { note: note.trim() }
    if (inv?.kind === 'digital') {
      const keys = values.split('\n').map((v) => v.trim()).filter(Boolean)
      if (!keys.length) {
        setMsg('Paste at least one key, one per line.')
        return
      }
      body.values = keys
    } else {
      const n = Number(qty)
      if (!Number.isInteger(n) || n < 0 || (mode === 'add' && n === 0)) {
        setMsg(mode === 'add' ? 'Enter a quantity above zero to add.' : 'Enter a quantity (0 or more) to set.')
        return
      }
      body.mode = mode
      body.qty = n
    }
    setBusy(true)
    setMsg('')
    try {
      const res = await fetch(`/api/products/${id}/restock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(json?.error || 'Restock failed')
        return
      }
      setInv(json.inventory)
      setMsg(
        inv?.kind === 'digital'
          ? `Added ${json.result?.added ?? 0} new key(s).`
          : `Stock is now ${json.result?.stock ?? '—'}.`,
      )
      setQty('')
      setValues('')
      setNote('')
    } finally {
      setBusy(false)
    }
  }

  if (!id) return null
  return (
    <div style={{ border: '1px solid var(--theme-elevation-150)', borderRadius: 6, padding: 16, marginTop: 16 }}>
      <h3 style={{ marginTop: 0 }}>Live Inventory (bot)</h3>
      {error && <p style={{ color: 'var(--theme-error-500)' }}>{error}</p>}
      {!inv && !error && <p>Loading…</p>}
      {inv && (
        <>
          <p style={{ fontSize: 18 }}>
            {inv.kind === 'digital' ? (
              <>
                Unused keys: <strong>{inv.is_unlimited ? '∞ (unlimited product)' : inv.unused_values}</strong>
              </>
            ) : (
              <>
                In stock: <strong>{inv.stock < 0 ? '∞ (unlimited)' : inv.stock}</strong>
              </>
            )}
            {'  ·  '}{inv.is_active ? 'Active' : 'Inactive'}
          </p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            {inv.kind === 'digital' ? (
              <textarea
                aria-label="New keys, one per line"
                placeholder={'Paste new keys, one per line'}
                value={values}
                onChange={(e) => setValues(e.target.value)}
                rows={4}
                style={{ flex: '1 1 260px' }}
              />
            ) : (
              <>
                <select
                  aria-label="Restock mode"
                  value={mode}
                  onChange={(e) => setMode(e.target.value as 'add' | 'set')}
                >
                  <option value="add">Add to stock</option>
                  <option value="set">Set stock to</option>
                </select>
                <input
                  aria-label="Quantity"
                  placeholder="Qty"
                  value={qty}
                  onChange={(e) => setQty(e.target.value)}
                  style={{ width: 90 }}
                />
              </>
            )}
            <input
              aria-label="Note (required)"
              placeholder="Note (required)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              style={{ flex: '1 1 200px' }}
            />
            <button type="button" disabled={busy} onClick={restock}>
              Restock
            </button>
          </div>
          {msg && <p>{msg}</p>}
        </>
      )}
    </div>
  )
}
