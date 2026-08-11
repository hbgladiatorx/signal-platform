// Admin console API — backed by the /admin/* router. Every call requires the
// caller to be an admin (the backend enforces this; a non-admin gets 403). The
// UI additionally hides these surfaces unless GET /me reports is_admin.
import { api } from "@/lib/api/client";

export interface AdminOverview {
  total_users: number;
  active_users: number;
  disabled_users: number;
  admins: number;
  users_with_broker_key: number;
  active_sessions: number;
  live_sessions: number;
  config: Record<string, boolean>;
}

export interface AdminUserRow {
  id: string;
  email: string | null;
  name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
  last_active_at: string | null;
  strategy_count: number;
  session_count: number;
  broker_key_count: number;
}

export interface AdminUserDetail {
  id: string;
  email: string | null;
  name: string | null;
  role: string;
  is_active: boolean;
  strategies: Array<Record<string, unknown>>;
  sessions: Array<Record<string, unknown>>;
  broker_keys: Array<Record<string, unknown>>;
}

export const getAdminOverview = () => api.get<AdminOverview>("/admin/overview");

export const listAdminUsers = () => api.get<AdminUserRow[]>("/admin/users");

export const getAdminUser = (id: string) =>
  api.get<AdminUserDetail>(`/admin/users/${id}`);

export const setUserRole = (id: string, role: "member" | "admin") =>
  api.post<AdminUserRow>(`/admin/users/${id}/role`, { role });

export const setUserActive = (id: string, is_active: boolean) =>
  api.post<AdminUserRow>(`/admin/users/${id}/active`, { is_active });

export const deleteAdminUser = (id: string) =>
  api.del<void>(`/admin/users/${id}`);

export const revokeUserCredential = (userId: string, credentialId: string) =>
  api.del<void>(`/admin/users/${userId}/credentials/${credentialId}`);
