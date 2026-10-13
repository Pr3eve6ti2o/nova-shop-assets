/**
 * Server-side client for the bot's internal API (store-credit plan,
 * Phase 3/4). The bot stays the single writer of money: Payload never
 * touches the bot database — it calls these endpoints instead.
 *
 * Configured via env (server-only, never exposed to the browser):
 *   NOVA_BOT_API_URL     e.g. http://127.0.0.1:8091
 *   NOVA_BOT_API_SECRET  the bot's INTERNAL_API_SECRET (>= 32 chars)
 */
import { randomUUID } from 'crypto'

export class BotApiError extends Error {
  status: number
  code?: string

  constructor(status: number, message: string, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

export function botApiConfigured(): boolean {
  return Boolean(process.env.NOVA_BOT_API_URL && process.env.NOVA_BOT_API_SECRET)
}

export async function botFetch(
  path: string,
  init: { method?: string; body?: unknown; idempotencyKey?: string } = {},
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): Promise<any> {
  const base = (process.env.NOVA_BOT_API_URL || '').replace(/\/$/, '')
  const secret = process.env.NOVA_BOT_API_SECRET || ''
  if (!base || !secret) {
    throw new BotApiError(503, 'Bot API is not configured (NOVA_BOT_API_URL / NOVA_BOT_API_SECRET).', 'not_configured')
  }
  const headers: Record<string, string> = {
    'X-Nova-Internal-Key': secret,
    'Content-Type': 'application/json',
  }
  if (init.idempotencyKey) headers['Idempotency-Key'] = init.idempotencyKey
  let res: Response
  try {
    res = await fetch(`${base}${path}`, {
      method: init.method || 'GET',
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    })
  } catch {
    throw new BotApiError(502, 'Bot API is unreachable.', 'unreachable')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new BotApiError(res.status, data?.error || `Bot API error ${res.status}`, data?.code)
  }
  return data
}

export const newIdempotencyKey = (): string => randomUUID()

/** The panel user's role, for endpoint-level checks. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function panelRole(req: any): string | undefined {
  return req?.user?.role as string | undefined
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function requireRole(req: any, roles: string[]): Response | null {
  const role = panelRole(req)
  if (!role || !roles.includes(role)) {
    return Response.json({ error: 'Forbidden' }, { status: 403 })
  }
  return null
}

/** Read a JSON request body in a Payload endpoint, tolerating absence. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function readJsonBody(req: any): Promise<Record<string, any>> {
  try {
    const data = req?.json ? await req.json() : {}
    return data && typeof data === 'object' ? data : {}
  } catch {
    return {}
  }
}

/** Wrap an endpoint handler body with BotApiError -> JSON mapping. */
export async function withBotErrors(fn: () => Promise<Response>): Promise<Response> {
  try {
    return await fn()
  } catch (e) {
    if (e instanceof BotApiError) {
      return Response.json({ error: e.message, code: e.code }, { status: e.status })
    }
    return Response.json({ error: 'Unexpected error' }, { status: 500 })
  }
}
