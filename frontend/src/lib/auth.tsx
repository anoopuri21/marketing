import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type ReactNode } from 'react'
import { Auth, TOKEN_KEY } from './api'
import { AuthContext, type AuthState } from './authContext'

const SESSION_KEY = ['auth', 'me'] as const

/**
 * Session provider. The current user is a react-query resource keyed on the token, so there is no
 * effect→setState synchronisation: logging in/out just swaps the token and lets the query refetch.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY))

  const session = useQuery({
    queryKey: [...SESSION_KEY, token],
    queryFn: async () => {
      try {
        return await Auth.me()
      } catch {
        localStorage.removeItem(TOKEN_KEY) // expired / invalid token – drop it
        return null
      }
    },
    enabled: !!token,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  const value = useMemo<AuthState>(() => {
    const me = token ? session.data ?? null : null
    const setSession = async (accessToken: string) => {
      localStorage.setItem(TOKEN_KEY, accessToken)
      // Seed the cache before switching tokens so protected routes render without a loading flash.
      qc.setQueryData([...SESSION_KEY, accessToken], await Auth.me())
      setToken(accessToken)
    }
    return {
      user: me?.user ?? null,
      workspaces: me?.workspaces ?? [],
      loading: !!token && session.isPending,
      login: async (email, password) => setSession((await Auth.login(email, password)).access_token),
      register: async (payload) => setSession((await Auth.register(payload)).access_token),
      logout: () => {
        localStorage.removeItem(TOKEN_KEY)
        setToken(null)
        qc.clear() // never leak one account's cached data into the next session
      },
    }
  }, [token, session.data, session.isPending, qc])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
