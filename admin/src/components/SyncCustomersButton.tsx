'use client'
import React, { useState } from 'react'

/** Customers list header action: pull the latest mirror from the bot. */
export default function SyncCustomersButton() {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const sync = async () => {
    setBusy(true)
    setMsg('')
    try {
      const res = await fetch('/api/customers/sync', { method: 'POST' })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(json?.error || 'Sync failed')
        return
      }
      setMsg(`Synced ${json.upserted} customer(s).`)
      window.location.reload()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '8px 0' }}>
      <button type="button" onClick={sync} disabled={busy}>
        {busy ? 'Syncing…' : 'Sync from bot'}
      </button>
      {msg && <span>{msg}</span>}
    </div>
  )
}
