import { Center, Loader } from '@mantine/core';
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { useAuth } from '../hooks/useAuth';

/** Renders its children only for a signed-in user; otherwise redirects to /login. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === 'loading') {
    return (
      <Center h="100vh">
        <Loader aria-label="Loading" />
      </Center>
    );
  }
  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

/** Admin pages: other users get the not-found page (as the API answers 403). */
export function RequireAdmin({ children, fallback }: { children: ReactNode; fallback: ReactNode }) {
  const { user } = useAuth();
  return <>{user?.role === 'admin' ? children : fallback}</>;
}

/** The opposite guard, for /login and /register: signed-in users go to the dashboard. */
export function RedirectIfAuthenticated({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  if (status === 'authenticated') return <Navigate to="/" replace />;
  return <>{children}</>;
}
