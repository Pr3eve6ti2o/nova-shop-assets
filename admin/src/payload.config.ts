import { sqliteAdapter } from '@payloadcms/db-sqlite'
import { lexicalEditor } from '@payloadcms/richtext-lexical'
import path from 'path'
import { buildConfig } from 'payload'
import { fileURLToPath } from 'url'
import sharp from 'sharp'

import { Users } from './collections/Users'
import { Media } from './collections/Media'
import { Categories } from './collections/Categories'
import { Products } from './collections/Products'
import { Orders } from './collections/Orders'

const filename = fileURLToPath(import.meta.url)
const dirname = path.dirname(filename)

export default buildConfig({
  admin: {
    user: Users.slug,
    importMap: {
      baseDir: path.resolve(dirname),
    },
  },
  collections: [Users, Media, Categories, Products, Orders],
  editor: lexicalEditor(),
  secret: (() => {
    const secret = process.env.PAYLOAD_SECRET
    if (!secret || secret.length < 32) throw new Error('PAYLOAD_SECRET must be set to at least 32 characters')
    return secret
  })(),
  typescript: {
    outputFile: path.resolve(dirname, 'payload-types.ts'),
  },
  db: sqliteAdapter({
    client: {
      url: process.env.DATABASE_URL || '',
    },
    // Improve SQLite behavior for concurrent admin requests. This is still
    // not a substitute for Postgres in a multi-process production topology.
    wal: true,
    busyTimeout: 5000,
  }),
  sharp,
  plugins: [],
})
