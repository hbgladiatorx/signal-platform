// The user's own AI provider for the copilot. Runs the copilot, strategy
// builder, tweak advisor, and narration on THEIR provider + key. Supports
// Anthropic or any OpenAI-compatible endpoint (OpenAI, DeepSeek, Groq,
// OpenRouter, custom). Stored encrypted via /settings/api-keys
// (service="ai_provider", payload {provider, api_key, base_url?, model?}).
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sparkles, Trash2, Plus } from "lucide-react";
import {
  AI_PROVIDERS,
  createApiCredential,
  deleteApiCredential,
  listApiCredentials,
  type ApiCredential,
} from "@/lib/api/settings";

const QK = ["apiCredentials"];
// Both the new provider config and the legacy key-only credential count as "AI".
const AI_SERVICES = new Set(["ai_provider", "anthropic"]);

export function AIProviderCard() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: QK, queryFn: listApiCredentials });

  const [providerKey, setProviderKey] = useState(AI_PROVIDERS[0].key);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(AI_PROVIDERS[0].defaultModel);
  const [baseUrl, setBaseUrl] = useState("");

  const preset = useMemo(
    () => AI_PROVIDERS.find((p) => p.key === providerKey) ?? AI_PROVIDERS[0],
    [providerKey],
  );

  const connected: ApiCredential | undefined = (data ?? []).find((c) => AI_SERVICES.has(c.service));

  const onProviderChange = (key: string) => {
    setProviderKey(key);
    const p = AI_PROVIDERS.find((x) => x.key === key);
    setModel(p?.defaultModel ?? "");
    setBaseUrl("");
  };

  const create = useMutation({
    mutationFn: async () => {
      // Replace any existing AI credential so exactly one provider is active.
      for (const c of (data ?? []).filter((x) => AI_SERVICES.has(x.service))) {
        await deleteApiCredential(c.id).catch(() => {});
      }
      const payload: Record<string, string> = { provider: providerKey, api_key: apiKey.trim() };
      if (model.trim()) payload.model = model.trim();
      const effectiveBase = preset.needsBaseUrl ? baseUrl.trim() : preset.baseUrl ?? "";
      if (effectiveBase) payload.base_url = effectiveBase;
      return createApiCredential({ service: "ai_provider", label: preset.label, payload });
    },
    onSuccess: () => {
      toast.success(`${preset.label} connected`);
      setApiKey("");
      qc.invalidateQueries({ queryKey: QK });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Could not save provider"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteApiCredential(id),
    onSuccess: () => { toast("AI provider removed"); qc.invalidateQueries({ queryKey: QK }); },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Could not remove provider"),
  });

  const canSubmit =
    apiKey.trim().length > 0 &&
    (!preset.needsBaseUrl || baseUrl.trim().length > 0) &&
    (preset.key === "anthropic" || model.trim().length > 0) &&
    !create.isPending;

  return (
    <Card className="border-border bg-elevated p-5">
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-violet" />
        <h2 className="font-semibold">AI copilot provider</h2>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        The copilot, strategy builder, and AI analysis run on <strong>your own</strong>{" "}
        provider — your usage bills to your account. Use Anthropic, or a cheaper
        OpenAI-compatible provider (DeepSeek, Groq, OpenRouter, OpenAI, or a custom
        endpoint). Stored encrypted; only the last 4 characters are shown.
      </p>
      <Separator className="my-4" />

      {error ? (
        <p className="text-sm text-destructive">Couldn't load your provider. {(error as Error).message}</p>
      ) : isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : connected ? (
        <div className="flex items-center justify-between rounded-md border border-border bg-background/40 px-3 py-2">
          <div className="min-w-0">
            <div className="text-sm font-medium">{connected.label || "AI provider"} connected</div>
            <div className="text-xs text-muted-foreground">
              {connected.last_four ? `••••${connected.last_four}` : "••••"} · added{" "}
              {new Date(connected.created_at).toLocaleDateString()}
            </div>
          </div>
          <Button size="icon" variant="ghost" disabled={remove.isPending}
            onClick={() => remove.mutate(connected.id)} aria-label="Remove AI provider">
            <Trash2 className="size-4 text-muted-foreground" />
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Provider</Label>
              <Select value={providerKey} onValueChange={onProviderChange}>
                <SelectTrigger className="bg-background"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {AI_PROVIDERS.map((p) => (
                    <SelectItem key={p.key} value={p.key}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {preset.hint && <p className="text-[11px] text-muted-foreground">Get a key: {preset.hint}</p>}
            </div>
            <div className="space-y-1.5">
              <Label>Model {preset.key === "anthropic" && <span className="text-muted-foreground">(optional)</span>}</Label>
              <Input className="bg-background font-mono" placeholder={preset.key === "anthropic" ? "default Claude" : "model id"}
                value={model} onChange={(e) => setModel(e.target.value)} />
            </div>
          </div>
          {preset.needsBaseUrl && (
            <div className="space-y-1.5">
              <Label>Base URL</Label>
              <Input className="bg-background font-mono" placeholder="https://your-endpoint/v1"
                value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
            </div>
          )}
          <div className="space-y-1.5">
            <Label>API key</Label>
            <Input className="bg-background font-mono" type="password" autoComplete="off"
              placeholder="sk-…" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          </div>
          <Button disabled={!canSubmit} onClick={() => create.mutate()}>
            <Plus className="mr-1 size-4" />
            {create.isPending ? "Connecting…" : "Connect provider"}
          </Button>
        </div>
      )}
    </Card>
  );
}

export default AIProviderCard;
