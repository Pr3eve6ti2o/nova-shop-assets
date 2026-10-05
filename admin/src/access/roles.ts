import type { Access } from 'payload'

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
