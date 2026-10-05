/**
 * Bootstrap script — run ONCE (safe to re-run):
 *   cd ~/workspace/nova-shop/admin && npx tsx src/scripts/create-sync-user.ts
 *
 * Creates:
 *  1. A first admin user (ADMIN_EMAIL/ADMIN_PASSWORD env or generated).
 *     Credentials are written to .admin-credentials (0600) — log in once, then rotate.
 *  2. A `sync@localhost` user (role=admin) with a fresh API key for bot<->Payload sync.
 *     The raw key is written to admin/.env as PAYLOAD_API_KEY (0600) and NEVER printed.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import dotenv from 'dotenv'

const here = path.dirname(fileURLToPath(import.meta.url))
const adminDir = path.resolve(here, '..', '..')
dotenv.config({ path: path.join(adminDir, '.env') })

const { getPayload } = await import('payload')
const { default: config } = await import('../payload.config.js')

const ADMIN_EMAIL = process.env.ADMIN_EMAIL || 'admin@example.com'

async function main() {
  const payload = await getPayload({ config })

  // --- 1. first admin user ---
  const found = await payload.find({
    collection: 'users',
    where: { email: { equals: ADMIN_EMAIL } },
    limit: 1,
    overrideAccess: true,
  })
  if (found.totalDocs === 0) {
    const password =
      process.env.ADMIN_PASSWORD || crypto.randomBytes(16).toString('hex')
    await payload.create({
      collection: 'users',
      data: { email: ADMIN_EMAIL, password, role: 'admin' },
      overrideAccess: true,
    })
    fs.writeFileSync(
      path.join(adminDir, '.admin-credentials'),
      `email=${ADMIN_EMAIL}\npassword=${password}\n`,
      { mode: 0o600 },
    )
    console.log(`admin user created: ${ADMIN_EMAIL} (password saved to .admin-credentials, mode 0600)`)
  } else {
    console.log(`admin user already exists: ${ADMIN_EMAIL}`)
  }

  // --- 2. sync user + API key ---
  const syncEmail = 'sync@example.com'
  const existing = await payload.find({
    collection: 'users',
    where: { email: { equals: syncEmail } },
    limit: 1,
    overrideAccess: true,
  })
  const apiKey = crypto.randomBytes(32).toString('hex')
  if (existing.totalDocs === 0) {
    await payload.create({
      collection: 'users',
      data: {
        email: syncEmail,
        password: crypto.randomBytes(24).toString('hex'),
        role: 'service',
        apiKey,
      },
      overrideAccess: true,
    })
    console.log('sync user created (sync@example.com)')
  } else {
    await payload.update({
      collection: 'users',
      id: existing.docs[0].id,
      data: { apiKey },
      overrideAccess: true,
    })
    console.log('sync user API key rotated (sync@example.com)')
  }

  // --- 3. persist key to admin/.env (0600), never print it ---
  const envPath = path.join(adminDir, '.env')
  let env = fs.readFileSync(envPath, 'utf8')
  if (/^PAYLOAD_API_KEY=/m.test(env)) {
    env = env.replace(/^PAYLOAD_API_KEY=.*$/m, `PAYLOAD_API_KEY=${apiKey}`)
  } else {
    if (!env.endsWith('\n')) env += '\n'
    env += `PAYLOAD_API_KEY=${apiKey}\n`
  }
  fs.writeFileSync(envPath, env, { mode: 0o600 })
  console.log('PAYLOAD_API_KEY written to admin/.env (mode 0600)')

  process.exit(0)
}

main().catch((err) => {
  console.error('bootstrap failed:', err?.message || err)
  process.exit(1)
})
