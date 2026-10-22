import { Navigate, Route, Routes } from 'react-router-dom';

import { AppLayout } from './components/AppLayout';
import { RedirectIfAuthenticated, RequireAdmin, RequireAuth } from './components/RequireAuth';
import { AdminConnectionsPage } from './pages/admin/AdminConnectionsPage';
import { AdminOrganizationsPage } from './pages/admin/AdminOrganizationsPage';
import { AdminProjectsPage } from './pages/admin/AdminProjectsPage';
import { AdminUsersPage } from './pages/admin/AdminUsersPage';
import { DashboardPage } from './pages/DashboardPage';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { ProjectDetailPage } from './pages/ProjectDetailPage';
import { RegisterPage } from './pages/RegisterPage';
import { RunDetailPage } from './pages/RunDetailPage';
import { AzureConnectionsPage } from './pages/settings/AzureConnectionsPage';
import { GitConnectionsPage } from './pages/settings/GitConnectionsPage';
import { OrganizationPage } from './pages/settings/OrganizationPage';
import { OrganizationsPage } from './pages/settings/OrganizationsPage';
import { ProfilePage } from './pages/settings/ProfilePage';
import { ProjectsPage } from './pages/settings/ProjectsPage';
import { ProjectWizardPage } from './pages/settings/ProjectWizardPage';

/** Opt in to React Router v7 behaviour now, so the later upgrade is a no-op. */
export const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

export function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <RedirectIfAuthenticated>
            <LoginPage />
          </RedirectIfAuthenticated>
        }
      />
      <Route
        path="/register"
        element={
          <RedirectIfAuthenticated>
            <RegisterPage />
          </RedirectIfAuthenticated>
        }
      />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="dashboard" element={<Navigate to="/" replace />} />
        <Route path="projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="projects/:projectId/runs/:runId" element={<RunDetailPage />} />
        <Route path="settings">
          <Route index element={<Navigate to="/settings/projects" replace />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="projects/new" element={<ProjectWizardPage />} />
          <Route path="projects/:projectId" element={<ProjectWizardPage />} />
          <Route path="git" element={<GitConnectionsPage />} />
          <Route path="azure" element={<AzureConnectionsPage />} />
          <Route path="organizations" element={<OrganizationsPage />} />
          <Route path="organizations/:organizationId" element={<OrganizationPage />} />
          <Route path="profile" element={<ProfilePage />} />
        </Route>
        <Route
          path="admin/users"
          element={
            <RequireAdmin fallback={<NotFoundPage />}>
              <AdminUsersPage />
            </RequireAdmin>
          }
        />
        <Route
          path="admin/projects"
          element={
            <RequireAdmin fallback={<NotFoundPage />}>
              <AdminProjectsPage />
            </RequireAdmin>
          }
        />
        <Route
          path="admin/connections"
          element={
            <RequireAdmin fallback={<NotFoundPage />}>
              <AdminConnectionsPage />
            </RequireAdmin>
          }
        />
        <Route
          path="admin/organizations"
          element={
            <RequireAdmin fallback={<NotFoundPage />}>
              <AdminOrganizationsPage />
            </RequireAdmin>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
