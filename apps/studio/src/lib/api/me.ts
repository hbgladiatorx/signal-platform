// Current-user identity — backed by GET /me. The canonical way the UI learns
// the signed-in user's platform record and, crucially, their role, so it can
// gate admin-only surfaces. Role is resolved server-side from the database.
import { api } from "@/lib/api/client";

export interface Me {
  id: string;
  org_id: string;
  email: string | null;
  role: string;
  is_active: boolean;
  is_admin: boolean;
}

export const getMe = () => api.get<Me>("/me");
