'use client'
import React, { useEffect, useState } from 'react'
import { useDocumentInfo } from '@payloadcms/ui'

/** Gift card detail action: revoke an active card (via the bot API). */
export default function GiftCardRevoke() {
  const { id } = useDocumentInfo()
  const [status, setStatus] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (!id) return
    fetch(`/api/gift-cards/${id}`)
      .then((r) => r.json())
      .then((doc) => setStatus(doc?.status || ''))
      .catch(() => setStatus(''))
  }, [id])

  const revoke = async () => {
    setBusy(true)
    try {
      const res = await fetch(`/api/gift-cards/${id}/revoke-via-bot`, { method: 'POST' })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(json?.error || 'Revoke failed')
        return
      }
      window.location.reload()
    } finally {
      setBusy(false)
    }
  }

  if (!id || status !== 'active') return null
  return (
    <div style={{ marginTop: 12 }}>
      <button type="button" onClick={revoke} disabled={busy}>
        Revoke gift card
      </button>
      {msg && <span style={{ marginLeft: 8 }}>{msg}</span>}
    </div>
  )
}
