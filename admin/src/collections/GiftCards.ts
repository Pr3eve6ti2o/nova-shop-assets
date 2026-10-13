import type { CollectionConfig } from 'payload'
import { isAdminOrService, isStaff } from '../access/roles'
import { botFetch, newIdempotencyKey, readJsonBody, requireRole, withBotErrors } from '../lib/botApi'

/**
 * Gift cards — mirror of the bot's gift_cards table.
 *
 * The BOT generates codes and owns redemption; this collection mirrors
 * rows for the panel. Creation/revocation go through custom endpoints
 * that call the bot's internal API (single source of truth), then the
 * mirror is refreshed from the API response.
 */
export const GiftCards: CollectionConfig = {
  slug: 'gift-cards',
  admin: {
    useAsTitle: 'code',
    defaultColumns: ['code', 'valueCents', 'remainingCents', 'status', 'expiresAt'],
    description: 'Stored-value gift cards. Create/revoke here — the bot generates codes and applies redemptions.',
    components: {
      beforeListTable: ['/components/GiftCardTools'],
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
          const { gift_cards } = await botFetch('/internal/gift-cards')
          let upserted = 0
          for (const g of gift_cards as Array<Record<string, unknown>>) {
            const data = mirrorData(g)
            const existing = await req.payload.find({
              collection: 'gift-cards',
              where: { botId: { equals: g.id } },
              limit: 1,
              overrideAccess: true,
            })
            if (existing.docs.length) {
              await req.payload.update({
                collection: 'gift-cards', id: existing.docs[0].id, data, overrideAccess: true,
              })
            } else {
              await req.payload.create({
                collection: 'gift-cards', data, overrideAccess: true,
              })
            }
            upserted++
          }
          return Response.json({ ok: true, upserted })
        })
      },
    },
    {
      path: '/create-via-bot',
      method: 'post',
      handler: async (req) => {
        const denied = requireRole(req, ['admin'])
        if (denied) return denied
        return withBotErrors(async () => {
          const body = await readJsonBody(req)
          const valueCents = Number(body?.valueCents)
          const expiresDays = body?.expiresDays === null || body?.expiresDays === undefined
            ? undefined : Number(body.expiresDays)
          if (!Number.isInteger(valueCents) || valueCents <= 0) {
            return Response.json({ error: 'valueCents must be a positive integer' }, { status: 400 })
          }
          const card = await botFetch('/internal/gift-cards', {
            method: 'POST',
            body: {
              value_cents: valueCents,
              expires_days: expiresDays,
              note: body?.note ? String(body.note) : undefined,
              actor: req.user?.email || `payload-user-${req.user?.id}`,
            },
            idempotencyKey: newIdempotencyKey(),
          })
          const doc = await req.payload.create({
            collection: 'gift-cards',
            data: mirrorData({ ...card, note: body?.note || null }),
            overrideAccess: true,
          })
          return Response.json({ ok: true, card, docId: doc.id })
        })
      },
    },
    {
      path: '/:id/revoke-via-bot',
      method: 'post',
      handler: async (req) => {
        const denied = requireRole(req, ['admin'])
        if (denied) return denied
        return withBotErrors(async () => {
          const doc = await req.payload.findByID({
            collection: 'gift-cards', id: req.routeParams?.id as string, overrideAccess: true,
          })
          await botFetch(`/internal/gift-cards/${doc.botId}/revoke`, {
            method: 'POST',
            body: { actor: req.user?.email || `payload-user-${req.user?.id}` },
            idempotencyKey: newIdempotencyKey(),
          })
          await req.payload.update({
            collection: 'gift-cards', id: doc.id,
            data: { status: 'revoked' }, overrideAccess: true,
          })
          return Response.json({ ok: true })
        })
      },
    },
  ],
  fields: [
    { name: 'botId', type: 'number', unique: true, index: true, admin: { readOnly: true } },
    { name: 'code', type: 'text', index: true, admin: { readOnly: true } },
    { name: 'valueCents', type: 'number', admin: { readOnly: true } },
    { name: 'remainingCents', type: 'number', admin: { readOnly: true } },
    {
      name: 'status',
      type: 'select',
      defaultValue: 'active',
      options: [
        { label: 'Active', value: 'active' },
        { label: 'Redeemed', value: 'redeemed' },
        { label: 'Revoked', value: 'revoked' },
        { label: 'Expired', value: 'expired' },
      ],
      admin: { readOnly: true },
    },
    { name: 'expiresAt', type: 'date', admin: { readOnly: true } },
    { name: 'note', type: 'text', admin: { readOnly: true } },
    { name: 'redeemedBy', type: 'text', admin: { readOnly: true, description: 'Bot user id that redeemed the card.' } },
    {
      name: 'revokeAction',
      type: 'ui',
      admin: {
        components: { Field: '/components/GiftCardRevoke' },
      },
    },
  ],
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function mirrorData(g: Record<string, any>) {
  return {
    botId: Number(g.id),
    code: String(g.code),
    valueCents: Number(g.value_cents),
    remainingCents: Number(g.remaining_cents),
    status: String(g.status) as 'active' | 'redeemed' | 'revoked' | 'expired',
    expiresAt: g.expires_at ? new Date(g.expires_at).toISOString() : null,
    note: g.note || null,
    redeemedBy: g.redeemed_by_user_id ? String(g.redeemed_by_user_id) : null,
  }
}
