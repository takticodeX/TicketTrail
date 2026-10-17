import { apiRequest } from './client';
import type { Page, User } from './types';

export interface AdminUser extends User {
  projects: number;
}

export const listUsers = (page: number, pageSize = 50) =>
  apiRequest<Page<AdminUser>>(`/admin/users?page=${page}&page_size=${pageSize}`);

export const setUserActive = (userId: string, isActive: boolean) =>
  apiRequest<AdminUser>(`/admin/users/${userId}`, { method: 'PATCH', body: { is_active: isActive } });
