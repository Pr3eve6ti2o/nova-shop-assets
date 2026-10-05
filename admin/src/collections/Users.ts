import type { CollectionConfig } from 'payload'
import { isAdmin } from '../access/roles'

export const Users: CollectionConfig = {
  slug: 'users',
  access: {
    read: isAdmin,
    create: isAdmin,
    update: isAdmin,
    delete: isAdmin,
    admin: ({ req }) => Boolean(req.user) && (req.user as { role?: string }).role === 'admin',
  },
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
      access: { create: isAdmin, update: isAdmin },
      required: true,
      defaultValue: 'staff',
      options: [
        { label: 'Admin', value: 'admin' },
        { label: 'Staff', value: 'staff' },
        { label: 'Service', value: 'service' },
      ],
      admin: {
        description: 'Admins can manage users and settings; staff manage catalog and orders.',
      },
    },
  ],
}
