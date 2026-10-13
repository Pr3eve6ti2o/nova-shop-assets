'use client'
import React, { useEffect, useState } from 'react'
import { useDocumentInfo } from '@payloadcms/ui'

const fmt = (cents: number) => `$${((cents || 0) / 100).toFixed(2)}`

/**
 * Order detail action (Medusa pattern): refund to the customer's
 * store credit instead of the original rail. Blank amount = the full
 * refundable remainder. The bot enforces the ceiling.
 */
export default function OrderRefund() {
  const { id } = useDocumentInfo()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [doc, setDoc] = useState<any>(null)
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (!id) return
    fetch(`/api/orders/${id}`)
      .then((r) => r.json())
      .then(setDoc)
      .catch(() => setDoc(null))
  }, [id])

  if (!id || !doc) return null
  const remaining = (doc.totalCents || 0) - (doc.refundedCents || 0)
  if (remaining <= 0 || doc.status === 'cancelled' || doc.status === 'refunded') {
    return null
  }

  const refund = async () => {
    setBusy(true)
    setMsg('')
    try {
      const cents = amount ? Math.round(parseFloat(amount) * 100) : undefined
      if (cents !== undefined && (!Number.isFinite(cents) || cents <= 0)) {
        setMsg('Enter a valid amount or leave it blank for the full remainder.')
        return
      }
      const res = await fetch(`/api/orders/${id}/refund-to-credit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amountCents: cents, note: note || undefined }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(json?.error || 'Refund failed')
        return
      }
      window.location.reload()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ border: '1px solid var(--theme-elevation-150)', borderRadius: 6, padding: 16, marginTop: 16 }}>
      <h3 style={{ marginTop: 0 }}>Refund to store credit</h3>
      <p>Refundable now: <strong>{fmt(remaining)}</strong> (of {fmt(doc.totalCents)})</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <input aria-label="Amount in USD (blank = all)" placeholder="Amount (blank = all)"
          value={amount} onChange={(e) => setAmount(e.target.value)} style={{ width: 170 }} />
        <input aria-label="Note (optional)" placeholder="Note" value={note}
          onChange={(e) => setNote(e.target.value)} style={{ flex: '1 1 160px' }} />
        <button type="button" onClick={refund} disabled={busy}>Refund to credit</button>
      </div>
      {msg && <p>{msg}</p>}
    </div>
  )
}
