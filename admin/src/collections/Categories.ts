import type { CollectionConfig } from 'payload'

export const Categories: CollectionConfig = {
  slug: 'categories',
  admin: {
    useAsTitle: 'name',
    defaultColumns: ['name', 'emoji', 'slug'],
  },
  access: {
    read: () => true,
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
      unique: true,
      index: true,
      admin: {
        description: 'URL-friendly identifier, e.g. "electronics". Auto-use the bot category name lowercased if unsure.',
      },
    },
    {
      name: 'emoji',
      type: 'text',
      admin: {
        description: 'Emoji shown next to the category in the bot, e.g. 📱',
      },
    },
  ],
}
