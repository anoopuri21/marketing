import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Auth, TOKEN_KEY, type User, type Workspace } from './api'

interface AuthState {
  user: User | null
  workspaces: Workspace[]
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (payload: { email: string; password: string; full_name: string; workspace_name?: string }) => Promise<void>
  logout: () => void
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    if (!localStorage.getItem(TOKEN_KEY)) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const me = await Auth.me()
      setUser(me.user)
      setWorkspaces(me.workspaces)
    } catch {
      localStorage.removeItem(TOKEN_KEY)
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const value = useMemo<AuthState>(
    () => ({
      user,
      workspaces,
      loading,
      login: async (email, password) => {
        const { access_token } = await Auth.login(email, password)
        localStorage.setItem(TOKEN_KEY, access_token)
        await load()
      },
      register: async (payload) => {
        const { access_token } = await Auth.register(payload)
        localStorage.setItem(TOKEN_KEY, access_token)
        await load()
      },
      logout: () => {
        localStorage.removeItem(TOKEN_KEY)
        setUser(null)
        setWorkspaces([])
      },
    }),
    [user, workspaces, loading, load],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
