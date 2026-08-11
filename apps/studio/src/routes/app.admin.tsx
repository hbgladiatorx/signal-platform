import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { getMe } from "@/lib/api/me";
import {
  getAdminOverview,
  listAdminUsers,
  getAdminUser,
  setUserRole,
  setUserActive,
  deleteAdminUser,
  revokeUserCredential,
  type AdminUserRow,
} from "@/lib/api/admin";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { ShieldCheck, Users, Activity, KeyRound, Eye, Trash2 } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

export const Route = createFileRoute("/app/admin")({
  head: () => ({ meta: [{ title: "Admin — Bayn" }] }),
  component: AdminPage,
});

function AdminPage() {
  const me = useQuery({ queryKey: ["me"], queryFn: getMe });

  if (me.isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  }
  // Server enforces this too (403); the UI just avoids showing a broken page.
  if (!me.data?.is_admin) {
    return (
      <div className="p-6">
        <Card className="mx-auto max-w-md border-border bg-elevated p-6 text-center">
          <ShieldCheck className="mx-auto mb-3 size-8 text-muted-foreground" />
          <h1 className="text-lg font-semibold">Admins only</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            You don't have access to the admin console.
          </p>
        </Card>
      </div>
    );
  }

  return <AdminConsole selfId={me.data.id} />;
}

function AdminConsole({ selfId }: { selfId: string }) {
  const qc = useQueryClient();
  const overview = useQuery({ queryKey: ["admin", "overview"], queryFn: getAdminOverview });
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: listAdminUsers });
  const [viewId, setViewId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminUserRow | null>(null);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["admin", "users"] });
    qc.invalidateQueries({ queryKey: ["admin", "overview"] });
  };

  const roleMut = useMutation({
    mutationFn: (v: { id: string; role: "member" | "admin" }) => setUserRole(v.id, v.role),
    onSuccess: () => { toast.success("Role updated"); invalidate(); },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Couldn't change role"),
  });
  const activeMut = useMutation({
    mutationFn: (v: { id: string; is_active: boolean }) => setUserActive(v.id, v.is_active),
    onSuccess: (_d, v) => { toast.success(v.is_active ? "Account enabled" : "Account disabled"); invalidate(); },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Couldn't update account"),
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteAdminUser(id),
    onSuccess: () => { toast.success("Account deleted"); setDeleteTarget(null); invalidate(); },
    onError: (e) => { toast.error(e instanceof Error ? e.message : "Couldn't delete account"); setDeleteTarget(null); },
  });

  const o = overview.data;

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <ShieldCheck className="size-6 text-violet" /> Admin console
        </h1>
        <p className="text-sm text-muted-foreground">
          Manage users, monitor the platform, and support accounts. Every action here is audit-logged.
        </p>
      </div>

      {/* Overview */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat icon={<Users className="size-4" />} label="Users" value={o?.total_users} sub={`${o?.active_users ?? "—"} active · ${o?.disabled_users ?? "—"} disabled`} />
        <Stat icon={<ShieldCheck className="size-4" />} label="Admins" value={o?.admins} />
        <Stat icon={<KeyRound className="size-4" />} label="With broker key" value={o?.users_with_broker_key} sub={`${o?.total_users ?? "—"} total`} />
        <Stat icon={<Activity className="size-4" />} label="Active sessions" value={o?.active_sessions} sub={`${o?.live_sessions ?? 0} live`} />
      </div>

      {/* Config health */}
      {o && (
        <Card className="border-border bg-elevated p-4">
          <div className="mb-2 text-xs font-mono uppercase tracking-wider text-muted-foreground">Platform config</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(o.config).map(([k, ok]) => (
              <span key={k} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${ok ? "border-emerald-500/30 text-emerald-500" : "border-amber-500/30 text-amber-500"}`}>
                <span className={`size-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-amber-500"}`} />
                {k.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* Users */}
      <Card className="overflow-hidden border-border bg-elevated">
        <div className="grid grid-cols-12 gap-2 border-b border-border px-4 py-2 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
          <div className="col-span-4">User</div>
          <div className="col-span-2">Role</div>
          <div className="col-span-1 text-right">Strats</div>
          <div className="col-span-1 text-right">Sessions</div>
          <div className="col-span-1 text-right">Keys</div>
          <div className="col-span-3 text-right">Actions</div>
        </div>
        <div className="divide-y divide-border">
          {users.data?.map((u) => (
            <div key={u.id} className="grid grid-cols-12 items-center gap-2 px-4 py-3 text-sm">
              <div className="col-span-4 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium">{u.email ?? "—"}</span>
                  {!u.is_active && <Badge variant="outline" className="border-red-500/40 text-red-500">disabled</Badge>}
                  {u.id === selfId && <Badge variant="secondary">you</Badge>}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {u.name || "—"} · joined {formatDistanceToNow(new Date(u.created_at), { addSuffix: true })}
                </div>
              </div>
              <div className="col-span-2">
                <select
                  className="h-8 rounded-md border border-border bg-background px-2 text-xs disabled:opacity-50"
                  value={u.role}
                  disabled={u.id === selfId || roleMut.isPending}
                  onChange={(e) => roleMut.mutate({ id: u.id, role: e.target.value as "member" | "admin" })}
                >
                  <option value="member">member</option>
                  <option value="admin">admin</option>
                </select>
              </div>
              <div className="col-span-1 text-right font-mono">{u.strategy_count}</div>
              <div className="col-span-1 text-right font-mono">{u.session_count}</div>
              <div className="col-span-1 text-right font-mono">{u.broker_key_count}</div>
              <div className="col-span-3 flex justify-end gap-1">
                <Button size="sm" variant="ghost" onClick={() => setViewId(u.id)} title="View / support">
                  <Eye className="size-3.5" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={u.id === selfId || activeMut.isPending}
                  onClick={() => activeMut.mutate({ id: u.id, is_active: !u.is_active })}
                >
                  {u.is_active ? "Disable" : "Enable"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-danger hover:text-danger"
                  disabled={u.id === selfId}
                  onClick={() => setDeleteTarget(u)}
                  title="Delete account"
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            </div>
          ))}
          {users.data?.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">No users yet.</div>
          )}
          {users.isLoading && (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">Loading users…</div>
          )}
        </div>
      </Card>

      <UserDetailSheet userId={viewId} onClose={() => setViewId(null)} onChanged={invalidate} />

      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this account?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently deletes <strong>{deleteTarget?.email}</strong> and all their strategies,
              backtests, sessions, and broker keys. This can't be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-danger text-danger-foreground hover:bg-danger/90"
              onClick={() => deleteTarget && deleteMut.mutate(deleteTarget.id)}
            >
              {deleteMut.isPending ? "Deleting…" : "Delete permanently"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function Stat({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value?: number; sub?: string }) {
  return (
    <Card className="border-border bg-elevated p-4">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">{icon}{label}</div>
      <div className="mt-1 font-mono text-2xl font-semibold">{value ?? "—"}</div>
      {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
    </Card>
  );
}

function UserDetailSheet({ userId, onClose, onChanged }: { userId: string | null; onClose: () => void; onChanged: () => void }) {
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ["admin", "user", userId],
    queryFn: () => getAdminUser(userId as string),
    enabled: !!userId,
  });

  const revoke = useMutation({
    mutationFn: (credId: string) => revokeUserCredential(userId as string, credId),
    onSuccess: () => {
      toast.success("Broker key revoked");
      qc.invalidateQueries({ queryKey: ["admin", "user", userId] });
      onChanged();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Couldn't revoke key"),
  });

  const d = detail.data;

  return (
    <Sheet open={!!userId} onOpenChange={(o) => { if (!o) onClose(); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{d?.email ?? "User"}</SheetTitle>
        </SheetHeader>
        {detail.isLoading ? (
          <p className="mt-4 text-sm text-muted-foreground">Loading…</p>
        ) : d ? (
          <div className="mt-4 space-y-5 text-sm">
            <div className="text-xs text-muted-foreground">
              {d.name || "No name"} · role <span className="font-mono">{d.role}</span> · {d.is_active ? "active" : "disabled"}
            </div>

            <Section title={`Broker keys (${d.broker_keys.length})`}>
              {d.broker_keys.length === 0 ? <Empty>No broker keys connected.</Empty> : d.broker_keys.map((k) => (
                <div key={String(k.id)} className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{String(k.label)} <span className="text-xs text-muted-foreground">({String(k.service)})</span></div>
                    <div className="text-xs text-muted-foreground">••••{String(k.last_four ?? "")}</div>
                  </div>
                  <Button size="sm" variant="ghost" className="text-danger hover:text-danger" disabled={revoke.isPending} onClick={() => revoke.mutate(String(k.id))}>
                    Revoke
                  </Button>
                </div>
              ))}
            </Section>

            <Section title={`Strategies (${d.strategies.length})`}>
              {d.strategies.length === 0 ? <Empty>No strategies.</Empty> : d.strategies.map((s) => (
                <div key={String(s.id)} className="rounded-md border border-border px-3 py-2">
                  <div className="font-medium">{String(s.name)}</div>
                  <div className="text-xs text-muted-foreground">{String(s.asset_class ?? "")}</div>
                </div>
              ))}
            </Section>

            <Section title={`Sessions (${d.sessions.length})`}>
              {d.sessions.length === 0 ? <Empty>No sessions.</Empty> : d.sessions.map((s) => (
                <div key={String(s.id)} className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                  <div className="truncate">{String(s.strategy_name)}</div>
                  <div className="text-xs text-muted-foreground">{String(s.mode)} · {String(s.status)}</div>
                </div>
              ))}
            </Section>
          </div>
        ) : (
          <p className="mt-4 text-sm text-muted-foreground">Couldn't load this user.</p>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-mono uppercase tracking-wider text-muted-foreground">{title}</div>
      {children}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-muted-foreground">{children}</p>;
}
