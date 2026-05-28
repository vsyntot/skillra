/**
 * TokenGate — wraps protected routes and redirects to /login if no session is stored.
 */
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

interface TokenGateProps {
  children: React.ReactNode
}

export default function TokenGate({ children }: TokenGateProps) {
  const location = useLocation()
  const { isAuthenticated } = useAuth()

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}
