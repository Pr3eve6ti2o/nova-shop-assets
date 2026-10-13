import type { Access, FieldAccess } from 'payload'

type UserLike = {
  role?: string
}

const roleOf = (user: unknown) => (user && typeof user === 'object')
  ? (user as UserLike).role
  : undefined

export const isAuthenticated: Access = ({ req }) => Boolean(req.user)

export const isAdmin: Access = ({ req }) => roleOf(req.user) === 'admin'

export const isStaff: Access = ({ req }) => {
  const role = roleOf(req.user)
  return role === 'admin' || role === 'staff'
}

export const isService: Access = ({ req }) => roleOf(req.user) === 'service'

export const isAdminOrService: Access = ({ req }) => {
  const role = roleOf(req.user)
  return role === 'admin' || role === 'service'
}

/**
 * Field-level variants. Collection `Access` and field `FieldAccess`
 * have incompatible argument types in Payload 3, so fields must use
 * these (the repo previously passed the Access helpers to fields,
 * which failed type-checking and blocked `next build`).
 */
export const isAdminField: FieldAccess = ({ req }) => roleOf(req.user) === 'admin'

export const isStaffField: FieldAccess = ({ req }) => {
  const role = roleOf(req.user)
  return role === 'admin' || role === 'staff'
}

export const isAdminOrServiceField: FieldAccess = ({ req }) => {
  const role = roleOf(req.user)
  return role === 'admin' || role === 'service'
}
