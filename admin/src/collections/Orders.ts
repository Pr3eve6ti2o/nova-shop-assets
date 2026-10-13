import type { CollectionConfig } from 'payload'
import { isAdmin, isAdminOrService, isStaff } from '../access/roles'
import { isAdminField, isAdminOrServiceField, isStaffField } from '../access/roles'
import { botFetch, newIdempotencyKey, readJsonBody, requireRole, withBotErrors } from '../lib/botApi'

/**
 * Orders are created by the Telegram bot via its API key (POST /api/orders).
 * Nobody may create orders from the admin panel: `create` only allows
 * requests authenticated with a `users API-Key` Authorization header
 * (the browser panel uses cookie auth, so the "Create" button stays hidden).
 *
 * Store-credit additions (Medusa borrow, 2026-10-14):
 * - Manual orders (comp / charge balance) are created through a custom
 *   endpoint that calls the bot's internal API; the bot is the writer.
 * - "Refund to store credit" calls the bot API (fail-closed ceiling
 *   lives there) and mirrors the refunded total back onto the doc.
 * - Buyer-info edits (name/phone/address) write back to the bot via a
 *   beforeChange hook while the order is still eligible; if the bot
 *   refuses, the panel save never happens — no silent drift.
 */

const BOT_STATUS_TO_PAYLOAD: Record<string, string> = {
  pending: 'pending',
  awaiting_payment: 'pending',
  confirmed: 'paid',
  processing: 'processing',
  shipped: 'shipped',
  delivered: 'completed',
  cancelled: 'cancelled',
  refunded: 'refunded',
}

function botOrderId(orderNumber: unknown): number | null {
  const m = /^NS-(\d+)$/.exec(String(orderNumber || ''))
  return m ? Number(m[1]) : null
}

export const Orders: CollectionConfig = {
  slug: 'orders',
  admin: {
    useAsTitle: 'orderNumber',
    defaultColumns: ['orderNumber', 'customerName', 'totalCents', 'paymentMethod', 'status'],
    components: {
      beforeListTable: ['/components/ManualOrderTools'],
    },
  },
  access: {
    read: isStaff,
    create: isAdminOrService,
    update: isStaff,
    delete: () => false,
  },
  hooks: {
    beforeChange: [
      async ({ data, originalDoc, req, operation }) => {
        // Only panel edits of buyer info write back — bot pushes
        // (service role) and endpoint updates (context flag) skip.
        // This runs BEFORE the save on purpose: the bot is asked
        // first, and if it refuses (e.g. order already shipped) the
        // hook throws and the panel save never happens — an
        // afterChange version of this hook demonstrably let the
        // document drift when the bot said no (E2E, 2026-10-14).
        if (operation !== 'update' || !originalDoc) return data
        if (req.context?.skipBotSync) return data
        const role = (req.user as { role?: string } | null)?.role
        if (role !== 'admin' && role !== 'staff') return data
        const oid = botOrderId(originalDoc.orderNumber)
        if (!oid) return data
        const changed: Record<string, unknown> = {}
        if (data.customerName !== undefined && data.customerName !== originalDoc.customerName) {
          changed.name = data.customerName
        }
        if (data.phone !== undefined && data.phone !== originalDoc.phone) {
          changed.phone = data.phone
        }
        if (data.address !== undefined && data.address !== originalDoc.address) {
          changed.address = data.address
        }
        if (!Object.keys(changed).length) return data
        try {
          await botFetch(`/internal/orders/${oid}/buyer`, {
            method: 'POST',
            body: changed,
          })
        } catch (e) {
          throw new Error(
            `Bot write-back failed (${(e as Error).message}). The order was NOT updated.`,
          )
        }
        return data
      },
    ],
  },
  endpoints: [
    {
      path: '/:id/refund-to-credit',
      method: 'post',
      handler: async (req) => {
        const denied = requireRole(req, ['admin'])
        if (denied) return denied
        return withBotErrors(async () => {
          const doc = await req.payload.findByID({
            collection: 'orders', id: req.routeParams?.id as string, overrideAccess: true,
          })
          const oid = botOrderId(doc.orderNumber)
          if (!oid) {
            return Response.json({ error: 'Order has no bot id' }, { status: 400 })
          }
          const body = await readJsonBody(req)
          const result = await botFetch(`/internal/orders/${oid}/refund-to-credit`, {
            method: 'POST',
            body: {
              amount_cents: body?.amountCents ? Number(body.amountCents) : undefined,
              note: body?.note ? String(body.note) : undefined,
              actor: req.user?.email || `payload-user-${req.user?.id}`,
            },
            idempotencyKey: newIdempotencyKey(),
          })
          await req.payload.update({
            collection: 'orders',
            id: doc.id,
            data: {
              refundedCents: result.total_refunded_cents,
              ...(result.status === 'refunded' ? { status: 'refunded' } : {}),
            },
            overrideAccess: true,
            context: { skipBotSync: true },
          })
          return Response.json({ ok: true, result })
        })
      },
    },
    {
      path: '/create-manual',
      method: 'post',
      handler: async (req) => {
        const denied = requireRole(req, ['admin'])
        if (denied) return denied
        return withBotErrors(async () => {
          const body = await readJsonBody(req)
          const tgUserId = Number(body?.tgUserId)
          const kind = body?.kind === 'balance' ? 'balance' : 'comp'
          const items = Array.isArray(body?.items) ? body.items : []
          if (!tgUserId || !items.length) {
            return Response.json({ error: 'tgUserId and items are required' }, { status: 400 })
          }
          const created = await botFetch('/internal/orders/manual', {
            method: 'POST',
            body: {
              tg_id: tgUserId,
              kind,
              items: items.map((i: { productId: number; qty: number }) => ({
                product_id: Number(i.productId),
                qty: Number(i.qty),
              })),
              note: body?.note ? String(body.note) : undefined,
              actor: req.user?.email || `payload-user-${req.user?.id}`,
            },
            idempotencyKey: newIdempotencyKey(),
          })
          const full = await botFetch(`/internal/orders/${created.order_id}`)
          const customer = await botFetch(`/internal/customers/${tgUserId}`).catch(() => null)
          const orderNumber = `NS-${created.order_id}`
          const data = {
            orderNumber,
            tgUserId: String(tgUserId),
            customerName: customer?.name || '',
            items: (full.items as Array<{ name: string; qty: number; price_cents: number }>).map((i) => ({
              productName: i.name,
              qty: i.qty,
              priceCents: i.price_cents,
            })),
            totalCents: Number(full.order.total_cents),
            currency: 'USD',
            paymentMethod: kind as 'comp' | 'balance',
            status: (BOT_STATUS_TO_PAYLOAD[full.order.status as string] || 'pending') as
              'pending' | 'paid' | 'processing' | 'shipped' | 'completed' | 'cancelled' | 'refunded',
            refundedCents: 0,
          }
          const existing = await req.payload.find({
            collection: 'orders',
            where: { orderNumber: { equals: orderNumber } },
            limit: 1,
            overrideAccess: true,
          })
          const doc = existing.docs.length
            ? await req.payload.update({
                collection: 'orders', id: existing.docs[0].id, data,
                overrideAccess: true, context: { skipBotSync: true },
              })
            : await req.payload.create({
                collection: 'orders', data,
                overrideAccess: true, context: { skipBotSync: true },
              })
          return Response.json({ ok: true, orderNumber, docId: doc.id })
        })
      },
    },
  ],
  fields: [
    {
      name: 'orderNumber',
      type: 'text',
      unique: true,
      index: true,
    },
    {
      name: 'tgUserId',
      type: 'text',
      admin: {
        description: 'Telegram user id of the buyer.',
      },
    },
    {
      name: 'customerName',
      type: 'text',
    },
    {
      name: 'phone',
      type: 'text',
      admin: {
        description: 'Buyer phone. Edits write back to the bot while the order is unshipped.',
      },
    },
    {
      name: 'address',
      type: 'text',
      admin: {
        description: 'Delivery address. Edits write back to the bot while the order is unshipped.',
      },
    },
    {
      name: 'items',
      type: 'array',
      fields: [
        { name: 'productName', type: 'text' },
        { name: 'qty', type: 'number' },
        { name: 'priceCents', type: 'number' },
      ],
    },
    {
      name: 'totalCents',
      type: 'number',
      access: { update: isAdminOrServiceField },
    },
    {
      name: 'refundedCents',
      type: 'number',
      defaultValue: 0,
      admin: {
        readOnly: true,
        description: 'Total refunded to store credit so far (USD cents).',
      },
    },
    {
      name: 'currency',
      type: 'text',
      access: { update: isAdminOrServiceField },
      defaultValue: 'USD',
    },
    {
      name: 'paymentMethod',
      type: 'select',
      access: { update: isAdminOrServiceField },
      options: [
        { label: 'Telegram Stars', value: 'stars' },
        { label: 'Card', value: 'card' },
        { label: 'CryptoBot', value: 'cryptobot' },
        { label: 'Self-custody crypto', value: 'crypto_self' },
        { label: 'Store credit (balance)', value: 'balance' },
        { label: 'Comp (free)', value: 'comp' },
      ],
    },
    {
      name: 'status',
      type: 'select',
      access: { update: isStaffField },
      defaultValue: 'pending',
      options: [
        { label: 'Pending', value: 'pending' },
        { label: 'Paid', value: 'paid' },
        { label: 'Processing', value: 'processing' },
        { label: 'Shipped', value: 'shipped' },
        { label: 'Completed', value: 'completed' },
        { label: 'Cancelled', value: 'cancelled' },
        { label: 'Refunded', value: 'refunded' },
      ],
    },
    {
      name: 'refundAction',
      type: 'ui',
      admin: {
        components: { Field: '/components/OrderRefund' },
      },
    },
    {
      name: 'rawPayload',
      type: 'json',
      access: { create: isAdminOrServiceField, read: isAdminField, update: isAdminOrServiceField },
      admin: {
        readOnly: true,
        description: 'Original order payload from the bot (debug).',
      },
    },
  ],
}
