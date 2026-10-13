import type { CollectionConfig } from 'payload'
import { isAdminOrService, isStaff } from '../access/roles'
import { botFetch, newIdempotencyKey, readJsonBody, requireRole, withBotErrors } from '../lib/botApi'

/**
 * Shop customers — a READ MODEL mirrored from the Telegram bot.
 *
 * The bot owns customers and all money state; this collection mirrors
 * identity + store-credit snapshots for the admin panel (Medusa's
 * Store Credits list pattern: customer, balance, total credits, total
 * debits). Money actions are custom endpoints that call the bot's
 * internal API — Payload never writes the bot database.
 */
export const Customers: CollectionConfig = {
  slug: 'customers',
  admin: {
    useAsTitle: 'fullName',
    defaultColumns: ['fullName', 'tgUserId', 'balanceCents', 'totalCreditsCents', 'totalDebitsCents'],
    description: 'Shop customers mirrored from the bot. Use Sync to refresh; credit/debit runs through the bot.',
    components: {
      beforeListTable: ['/components/SyncCustomersButton'],
    },
  },
  access: {
    read: isStaff,
    create: isAdminOrService,
    update: isAdminOrService,
    delete: () => false,
  },
  endpoints: [
    {
      path: '/sync',
      method: 'post',
      handler: async (req) => {
        const denied = requireRole(req, ['admin', 'staff'])
        if (denied) return denied
        return withBotErrors(async () => {
          const { customers } = await botFetch('/internal/customers?limit=500')
          let upserted = 0
          for (const c of customers as Array<Record<string, unknown>>) {
            let stats: Record<string, number> = {}
            try {
              stats = await botFetch(`/internal/customers/${c.tg_id}`)
            } catch {
              stats = {}
            }
            const data = {
              tgUserId: String(c.tg_id),
              fullName: (c.name as string) || '',
              balanceCents: stats.balance_cents ?? c.balance_cents,
              totalCreditsCents: stats.total_credits_cents ?? 0,
              totalDebitsCents: stats.total_debits_cents ?? 0,
              txCount: stats.transactions ?? 0,
              blocked: Boolean(c.is_blocked),
            }
            const existing = await req.payload.find({
              collection: 'customers',
              where: { tgUserId: { equals: data.tgUserId } },
              limit: 1,
              overrideAccess: true,
            })
            if (existing.docs.length) {
              await req.payload.update({
                collection: 'customers', id: existing.docs[0].id, data, overrideAccess: true,
              })
            } else {
              await req.payload.create({
                collection: 'customers', data, overrideAccess: true,
              })
            }
            upserted++
          }
          return Response.json({ ok: true, upserted })
        })
      },
    },
    {
      path: '/:id/store-credit',
      method: 'get',
      handler: async (req) => {
        const denied = requireRole(req, ['admin', 'staff'])
        if (denied) return denied
        return withBotErrors(async () => {
          const doc = await req.payload.findByID({
            collection: 'customers', id: req.routeParams?.id as string, overrideAccess: true,
          })
          const account = await botFetch(`/internal/customers/${doc.tgUserId}`)
          const { transactions } = await botFetch(
            `/internal/customers/${doc.tgUserId}/transactions?limit=50`)
          return Response.json({ account, transactions })
        })
      },
    },
    {
      path: '/:id/credit',
      method: 'post',
      handler: async (req) => {
        const denied = requireRole(req, ['admin'])
        if (denied) return denied
        return adjustHandler(req, 'credit')
      },
    },
    {
      path: '/:id/debit',
      method: 'post',
      handler: async (req) => {
        const denied = requireRole(req, ['admin'])
        if (denied) return denied
        return adjustHandler(req, 'debit')
      },
    },
  ],
  fields: [
    { name: 'tgUserId', type: 'text', unique: true, index: true, admin: { readOnly: true } },
    { name: 'fullName', type: 'text', admin: { readOnly: true } },
    { name: 'balanceCents', type: 'number', defaultValue: 0, admin: { readOnly: true, description: 'Store-credit balance snapshot (USD cents).' } },
    { name: 'totalCreditsCents', type: 'number', defaultValue: 0, admin: { readOnly: true } },
    { name: 'totalDebitsCents', type: 'number', defaultValue: 0, admin: { readOnly: true } },
    { name: 'txCount', type: 'number', defaultValue: 0, admin: { readOnly: true } },
    { name: 'blocked', type: 'checkbox', defaultValue: false, admin: { readOnly: true } },
    {
      name: 'storeCredit',
      type: 'ui',
      admin: {
        components: { Field: '/components/StoreCreditPanel' },
      },
    },
  ],
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function adjustHandler(req: any, kind: 'credit' | 'debit'): Promise<Response> {
  return withBotErrors(async () => {
    const body = await readJsonBody(req)
    const amountCents = Number(body?.amountCents)
    const note = String(body?.note || '').trim()
    if (!Number.isInteger(amountCents) || amountCents <= 0) {
      return Response.json({ error: 'amountCents must be a positive integer' }, { status: 400 })
    }
    if (!note) {
      return Response.json({ error: 'A note is required' }, { status: 400 })
    }
    const doc = await req.payload.findByID({
      collection: 'customers', id: req.routeParams?.id as string, overrideAccess: true,
    })
    const result = await botFetch(`/internal/customers/${doc.tgUserId}/${kind}`, {
      method: 'POST',
      body: {
        amount_cents: amountCents,
        note,
        actor: req.user?.email || `payload-user-${req.user?.id}`,
      },
      idempotencyKey: newIdempotencyKey(),
    })
    // Refresh the snapshot fields from the bot's account view.
    const account = await botFetch(`/internal/customers/${doc.tgUserId}`)
    await req.payload.update({
      collection: 'customers',
      id: doc.id,
      data: {
        balanceCents: account.balance_cents,
        totalCreditsCents: account.total_credits_cents,
        totalDebitsCents: account.total_debits_cents,
        txCount: account.transactions,
      },
      overrideAccess: true,
    })
    return Response.json({ ok: true, result, account })
  })
}
