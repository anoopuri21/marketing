import { createContext, useContext } from 'react'
import type { User, Workspace } from './api'

export interface AuthState {
  user: User | null
  workspaces: Workspace[]
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (payload: { email: string; password: string; full_name: string; workspace_name?: string }) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
