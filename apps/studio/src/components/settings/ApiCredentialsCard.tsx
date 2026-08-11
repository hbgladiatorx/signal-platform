// Broker / data API credentials, backed by the FastAPI /settings/api-keys
// endpoint. Secrets are encrypted at rest server-side; only the last four
// characters of the primary key ever come back. These credentials are what a
// live/paper trading session routes orders through.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { KeyRound, Trash2, Plus } from "lucide-react";
import {
  CREDENTIAL_SERVICES,
  createApiCredential,
  deleteApiCredential,
  listApiCredentials,
  type ApiCredential,
} from "@/lib/api/settings";

const QK = ["apiCredentials"];

export function ApiCredentialsCard() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: QK,
    queryFn: listApiCredentials,
  });

  const [service, setService] = useState(CREDENTIAL_SERVICES[0].service);
  const [label, setLabel] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});

  const spec = CREDENTIAL_SERVICES.find((s) => s.service === service)!;

  const create = useMutation({
    mutationFn: () =>
      createApiCredential({ service, label: label.trim(), payload: fields }),
    onSuccess: () => {
      toast.success(`${spec.displayName} key added`);
      setLabel("");
      setFields({});
      qc.invalidateQueries({ queryKey: QK });
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "Could not add credential"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteApiCredential(id),
    onSuccess: () => {
      toast("Credential removed");
      qc.invalidateQueries({ queryKey: QK });
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "Could not remove credential"),
  });

  const canSubmit =
    label.trim().length > 0 &&
    spec.fields.every((f) => (fields[f.key] ?? "").trim().length > 0) &&
    !create.isPending;

  // Broker keys only — the AI provider keys have their own card.
  const creds: ApiCredential[] = (data ?? []).filter(
    (c) => c.service !== "anthropic" && c.service !== "ai_provider",
  );

  return (
    <Card className="border-border bg-elevated p-5">
      <div className="flex items-center gap-2">
        <KeyRound className="size-4 text-cyan" />
        <h2 className="font-semibold">Broker API keys</h2>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        Connect your own broker to run strategies on live data — every strategy
        you deploy trades on your account, using your key. Alpaca runs paper
        sessions; Binance.US trades real money. Keys are encrypted at rest,
        private to you, and only the last four characters are ever shown back.
      </p>
      <Separator className="my-4" />

      {error ? (
        <p className="text-sm text-destructive">
          Couldn't load your credentials. {(error as Error).message}
        </p>
      ) : isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : creds.length === 0 ? (
        <p className="text-sm text-muted-foreground">No API keys connected yet.</p>
      ) : (
        <ul className="space-y-2">
          {creds.map((c) => (
            <li
              key={c.id}
              className="flex items-center justify-between rounded-md border border-border bg-background/40 px-3 py-2"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <span className="truncate">{c.label}</span>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                    {c.service}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {c.last_four ? `••••${c.last_four}` : "—"} · added{" "}
                  {new Date(c.created_at).toLocaleDateString()}
                </div>
              </div>
              <Button
                size="icon"
                variant="ghost"
                disabled={remove.isPending}
                onClick={() => remove.mutate(c.id)}
                aria-label={`Remove ${c.label}`}
              >
                <Trash2 className="size-4 text-muted-foreground" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <Separator className="my-4" />

      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Broker</Label>
            <Select
              value={service}
              onValueChange={(v) => {
                setService(v);
                setFields({});
              }}
            >
              <SelectTrigger className="bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CREDENTIAL_SERVICES.map((s) => (
                  <SelectItem key={s.service} value={s.service}>
                    {s.displayName}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Label</Label>
            <Input
              className="bg-background"
              placeholder="e.g. Alpaca paper"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {spec.fields.map((f) => (
            <div key={f.key} className="space-y-1.5">
              <Label>{f.label}</Label>
              <Input
                className="bg-background font-mono"
                type={f.secret ? "password" : "text"}
                autoComplete="off"
                value={fields[f.key] ?? ""}
                onChange={(e) =>
                  setFields((prev) => ({ ...prev, [f.key]: e.target.value }))
                }
              />
            </div>
          ))}
        </div>
        <Button disabled={!canSubmit} onClick={() => create.mutate()}>
          <Plus className="mr-1 size-4" />
          {create.isPending ? "Adding…" : "Add key"}
        </Button>
      </div>
    </Card>
  );
}

export default ApiCredentialsCard;
