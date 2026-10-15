import type { CollectionConfig } from 'payload'
import { isAdmin, isStaff } from '../access/roles'
import { isAdminField, isStaffField } from '../access/roles'
import { botFetch, newIdempotencyKey, readJsonBody, requireRole, withBotErrors } from '../lib/botApi'

export const Products: CollectionConfig = {
  slug: 'products',
  admin: {
    useAsTitle: 'name',
    defaultColumns: ['name', 'priceCents', 'status', 'stock', 'category'],
  },
  access: {
    // Public storefront reads; writes restricted to logged-in users / API-key sync
    read: () => true,
    create: isStaff,
    update: isStaff,
    delete: isAdmin,
  },
  fields: [
    {
      name: 'name',
      type: 'text',
      required: true,
    },
    {
      name: 'slug',
      type: 'text',
      required: true,
      unique: true,
      index: true,
    },
    {
      name: 'description',
      type: 'textarea',
    },
    {
      name: 'priceCents',
      type: 'number',
      required: true,
      min: 0,
      admin: {
        description: 'Price in the smallest currency unit (cents).',
      },
    },
    {
      name: 'oldPriceCents',
      type: 'number',
      min: 0,
      admin: {
        description: 'Optional strikethrough price in cents (for sales).',
      },
    },
    {
      name: 'kind',
      type: 'select',
      defaultValue: 'physical',
      options: [
        { label: 'Physical', value: 'physical' },
        { label: 'Digital', value: 'digital' },
      ],
    },
    {
      name: 'stock',
      type: 'number',
      access: { update: isStaffField },
      defaultValue: -1,
      admin: {
        description:
          '-1 = unlimited stock. This value only seeds a NEW product when it first syncs to the bot — live stock is owned by the bot and is managed in the Live Inventory section below (catalogue sync no longer overwrites it).',
      },
    },
    {
      name: 'category',
      type: 'relationship',
      relationTo: 'categories',
    },
    {
      name: 'status',
      type: 'select',
      access: { update: isAdminField },
      defaultValue: 'draft',
      options: [
        { label: 'Draft', value: 'draft' },
        { label: 'Published', value: 'published' },
      ],
      admin: {
        description: 'Only "Published" products sync down to the Telegram bot.',
      },
    },
    {
      name: 'featured',
      type: 'checkbox',
      access: { update: isStaffField },
    },
    {
      name: 'ratingSum',
      type: 'number',
      admin: {
        readOnly: true,
        description: 'Synced from bot reviews.',
      },
    },
    {
      name: 'ratingCount',
      type: 'number',
      admin: {
        readOnly: true,
        description: 'Synced from bot reviews.',
      },
    },
    {
      name: 'botId',
      type: 'number',
      unique: true,
      index: true,
      admin: {
        readOnly: true,
        description: 'Linked Telegram bot product id — managed by sync',
      },
    },
    {
      name: 'liveInventory',
      type: 'ui',
      admin: {
        components: { Field: '/components/InventoryPanel' },
      },
    },
  ],
  endpoints: [
    {
      path: '/:id/inventory',
      method: 'get',
      handler: async (req) => {
        const denied = requireRole(req, ['admin', 'staff'])
        if (denied) return denied
        return withBotErrors(async () => {
          const botId = await linkedBotId(req)
          if (botId === null) {
            return Response.json(
              { error: 'This product is not linked to a bot product yet — run the catalogue sync first.' },
              { status: 409 })
          }
          const inventory = await botFetch(`/internal/products/${botId}`)
          return Response.json({ inventory })
        })
      },
    },
    {
      path: '/:id/restock',
      method: 'post',
      handler: async (req) => {
        const denied = requireRole(req, ['admin', 'staff'])
        if (denied) return denied
        return withBotErrors(async () => {
          const botId = await linkedBotId(req)
          if (botId === null) {
            return Response.json(
              { error: 'This product is not linked to a bot product yet — run the catalogue sync first.' },
              { status: 409 })
          }
          const body = await readJsonBody(req)
          const note = String(body?.note || '').trim()
          if (!note) {
            return Response.json({ error: 'A note is required' }, { status: 400 })
          }
          // Shape is validated again by the bot's internal API; here we
          // only forward the fields for this product's kind.
          const result = await botFetch(`/internal/products/${botId}/restock`, {
            method: 'POST',
            body: {
              mode: body?.mode,
              qty: body?.qty,
              values: body?.values,
              note,
              actor: req.user?.email || `payload-user-${req.user?.id}`,
            },
            idempotencyKey: newIdempotencyKey(),
          })
          const inventory = await botFetch(`/internal/products/${botId}`)
          return Response.json({ ok: true, result, inventory })
        })
      },
    },
  ],
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function linkedBotId(req: any): Promise<number | null> {
  const doc = await req.payload.findByID({
    collection: 'products', id: req.routeParams?.id as string, overrideAccess: true,
  })
  const botId = Number(doc?.botId)
  return Number.isInteger(botId) && botId > 0 ? botId : null
}
