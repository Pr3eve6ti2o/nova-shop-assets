'use client'
import React, { useState } from 'react'

/**
 * Gift Cards list header: create a card (the BOT generates the code
 * via its internal API) and sync the mirror from the bot.
 */
export default function GiftCardTools() {
  const [value, setValue] = useState('')
  const [days, setDays] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [code, setCode] = useState('')

  const create = async () => {
    const cents = Math.round(parseFloat(value) * 100)
    if (!Number.isFinite(cents) || cents <= 0) {
      setMsg('Enter a valid value.')
      return
    }
    setBusy(true)
    setMsg('')
    setCode('')
    try {
      const res = await fetch('/api/gift-cards/create-via-bot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          valueCents: cents,
          expiresDays: days ? Number(days) : undefined,
          note: note || undefined,
        }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(json?.error || 'Create failed')
        return
      }
      setCode(json.card.code)
      setMsg('Gift card created:')
      setValue('')
      setDays('')
      setNote('')
    } finally {
      setBusy(false)
    }
  }

  const sync = async () => {
    setBusy(true)
    try {
      const res = await fetch('/api/gift-cards/sync', { method: 'POST' })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(json?.error || 'Sync failed')
        return
      }
      setMsg(`Synced ${json.upserted} gift card(s).`)
      window.location.reload()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', margin: '8px 0' }}>
      <input aria-label="Value in USD" placeholder="Value (USD)" value={value}
        onChange={(e) => setValue(e.target.value)} style={{ width: 110 }} />
      <input aria-label="Expiry days (optional)" placeholder="Expiry days" value={days}
        onChange={(e) => setDays(e.target.value)} style={{ width: 100 }} />
      <input aria-label="Note (optional)" placeholder="Note" value={note}
        onChange={(e) => setNote(e.target.value)} style={{ width: 160 }} />
      <button type="button" onClick={create} disabled={busy}>New gift card</button>
      <button type="button" onClick={sync} disabled={busy}>Sync from bot</button>
      {msg && <span>{msg}</span>}
      {code && <code style={{ fontWeight: 700 }}>{code}</code>}
    </div>
  )
}
