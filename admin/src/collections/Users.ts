import type { CollectionConfig } from 'payload'

export const Users: CollectionConfig = {
  slug: 'users',
  admin: {
    useAsTitle: 'email',
  },
  auth: {
    // Enables per-user API keys for server-to-server sync (bot -> Payload).
    // Header format:  Authorization: users API-Key <key>
    useAPIKey: true,
  },
  fields: [
    {
      name: 'role',
      type: 'select',
      required: true,
      defaultValue: 'staff',
      options: [
        { label: 'Admin', value: 'admin' },
        { label: 'Staff', value: 'staff' },
      ],
      admin: {
        description: 'Admins can manage users and settings; staff manage catalog and orders.',
      },
    },
  ],
}
