'use client'
import React, { useCallback, useEffect, useState } from 'react'
import { useDocumentInfo } from '@payloadcms/ui'

const fmt = (cents: number) => `$${((cents || 0) / 100).toFixed(2)}`

type Tx = {
  id: number
  type: string
  amount_cents: number
  balance_after_cents: number
  note?: string
  actor_type?: string
  reference?: string
  created_at?: string
}

/**
 * Store Credit section on the Customer detail (Medusa admin pattern):
 * balance + totals, credit/debit actions with a mandatory note, and
 * the transaction history. All actions call Payload endpoints that
 * proxy the bot's internal API — the bot moves the money.
 */
export default function StoreCreditPanel() {
  const { id } = useDocumentInfo()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    if (!id) return
    try {
      const res = await fetch(`/api/customers/${id}/store-credit`)
      const json = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(json?.error || 'Failed to load store credit')
        return
      }
      setData(json)
      setError('')
    } catch {
      setError('Failed to load store credit')
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const act = async (kind: 'credit' | 'debit') => {
    const cents = Math.round(parseFloat(amount) * 100)
    if (!Number.isFinite(cents) || cents <= 0) {
      setMsg('Enter a valid amount.')
      return
    }
    if (!note.trim()) {
      setMsg('A note is required — it goes on the ledger.')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const res = await fetch(`/api/customers/${id}/${kind}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amountCents: cents, note: note.trim() }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(json?.error || 'Action failed')
        return
      }
      setMsg(`${kind === 'credit' ? 'Credited' : 'Debited'} ${fmt(cents)}.`)
      setAmount('')
      setNote('')
      void load()
    } finally {
      setBusy(false)
    }
  }

  if (!id) return null
  return (
    <div style={{ border: '1px solid var(--theme-elevation-150)', borderRadius: 6, padding: 16, marginTop: 16 }}>
      <h3 style={{ marginTop: 0 }}>Store Credit</h3>
      {error && <p style={{ color: 'var(--theme-error-500)' }}>{error}</p>}
      {!data && !error && <p>Loading…</p>}
      {data && (
        <>
          <p style={{ fontSize: 18 }}>
            Balance: <strong>{fmt(data.account.balance_cents)}</strong>
            {'  ·  '}Total credits: {fmt(data.account.total_credits_cents)}
            {'  ·  '}Total debits: {fmt(data.account.total_debits_cents)}
          </p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <input
              aria-label="Amount in USD"
              placeholder="Amount (USD)"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              style={{ width: 130 }}
            />
            <input
              aria-label="Note (required)"
              placeholder="Note (required)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              style={{ flex: '1 1 200px' }}
            />
            <button type="button" disabled={busy} onClick={() => act('credit')}>
              Credit
            </button>
            <button
              type="button"
              disabled={busy || !data.account.balance_cents}
              onClick={() => act('debit')}
              title={data.account.balance_cents ? '' : 'Nothing to debit'}
            >
              Debit
            </button>
          </div>
          {msg && <p>{msg}</p>}
          <table style={{ width: '100%', marginTop: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th align="left">When</th>
                <th align="left">Type</th>
                <th align="right">Amount</th>
                <th align="right">Balance after</th>
                <th align="left">Note</th>
                <th align="left">Actor</th>
              </tr>
            </thead>
            <tbody>
              {(data.transactions as Tx[]).map((t) => (
                <tr key={t.id} style={{ borderTop: '1px solid var(--theme-elevation-100)' }}>
                  <td>{t.created_at || ''}</td>
                  <td>{t.type}</td>
                  <td align="right">{fmt(t.amount_cents)}</td>
                  <td align="right">{fmt(t.balance_after_cents)}</td>
                  <td>{t.note || ''}</td>
                  <td>{t.actor_type || ''}</td>
                </tr>
              ))}
              {!data.transactions.length && (
                <tr>
                  <td colSpan={6}>No transactions yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
