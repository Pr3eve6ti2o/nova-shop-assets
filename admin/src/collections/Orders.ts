import type { CollectionConfig } from 'payload'
import { isAdmin, isAdminOrService, isStaff } from '../access/roles'

/**
 * Orders are created by the Telegram bot via its API key (POST /api/orders).
 * Nobody may create orders from the admin panel: `create` only allows
 * requests authenticated with a `users API-Key` Authorization header
 * (the browser panel uses cookie auth, so the "Create" button stays hidden).
 */
export const Orders: CollectionConfig = {
  slug: 'orders',
  admin: {
    useAsTitle: 'orderNumber',
    defaultColumns: ['orderNumber', 'customerName', 'totalCents', 'paymentMethod', 'status'],
  },
  access: {
    read: isStaff,
    create: isAdminOrService,
    update: isStaff,
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
      access: { update: isAdminOrService },
    },
    {
      name: 'currency',
      type: 'text',
      access: { update: isAdminOrService },
      defaultValue: 'USD',
    },
    {
      name: 'paymentMethod',
      type: 'select',
      access: { update: isAdminOrService },
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
      access: { update: isStaff },
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
      access: { create: isAdminOrService, read: isAdmin, update: isAdminOrService },
      admin: {
        readOnly: true,
        description: 'Original order payload from the bot (debug).',
      },
    },
  ],
}
