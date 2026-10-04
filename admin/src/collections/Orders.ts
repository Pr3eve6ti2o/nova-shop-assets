import type { CollectionConfig } from 'payload'

/**
 * Orders are created by the Telegram bot via its API key (POST /api/orders).
 * Nobody may create orders from the admin panel: `create` only allows
 * requests authenticated with a `users API-Key` Authorization header
 * (the browser panel uses cookie auth, so the "Create" button stays hidden).
 */
const isApiKeyRequest = ({ req }: { req: { headers?: { get?: (k: string) => string | null } } }) => {
  try {
    const h = req?.headers?.get?.('authorization') || ''
    return h.startsWith('users API-Key ')
  } catch {
    return false
  }
}

const isLoggedIn = ({ req }: { req: { user?: unknown } }) => Boolean(req?.user)

export const Orders: CollectionConfig = {
  slug: 'orders',
  admin: {
    useAsTitle: 'orderNumber',
    defaultColumns: ['orderNumber', 'customerName', 'totalCents', 'paymentMethod', 'status'],
  },
  access: {
    read: isLoggedIn,
    create: isApiKeyRequest,
    update: isLoggedIn,
    delete: () => false,
  },
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
    },
    {
      name: 'currency',
      type: 'text',
      defaultValue: 'USD',
    },
    {
      name: 'paymentMethod',
      type: 'select',
      options: [
        { label: 'Telegram Stars', value: 'stars' },
        { label: 'Card', value: 'card' },
        { label: 'CryptoBot', value: 'cryptobot' },
        { label: 'Self-custody crypto', value: 'crypto_self' },
      ],
    },
    {
      name: 'status',
      type: 'select',
      defaultValue: 'pending',
      options: [
        { label: 'Pending', value: 'pending' },
        { label: 'Paid', value: 'paid' },
        { label: 'Processing', value: 'processing' },
        { label: 'Shipped', value: 'shipped' },
        { label: 'Completed', value: 'completed' },
        { label: 'Cancelled', value: 'cancelled' },
      ],
    },
    {
      name: 'rawPayload',
      type: 'json',
      admin: {
        readOnly: true,
        description: 'Original order payload from the bot (debug).',
      },
    },
  ],
}
