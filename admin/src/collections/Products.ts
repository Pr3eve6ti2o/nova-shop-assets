import type { CollectionConfig } from 'payload'

export const Products: CollectionConfig = {
  slug: 'products',
  admin: {
    useAsTitle: 'name',
    defaultColumns: ['name', 'priceCents', 'status', 'stock', 'category'],
  },
  access: {
    // Public storefront reads; writes restricted to logged-in users / API-key sync
    read: () => true,
    create: ({ req }) => Boolean(req?.user),
    update: ({ req }) => Boolean(req?.user),
    delete: ({ req }) => Boolean(req?.user),
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
      defaultValue: -1,
      admin: {
        description: '-1 = unlimited stock.',
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
  ],
}
