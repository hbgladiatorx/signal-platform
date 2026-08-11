// The user's own Anthropic (AI copilot) API key. The copilot, strategy builder,
// tweak advisor, and result narration all run on THIS key — each user brings
// their own, and their AI usage bills to their own Anthropic account. Backed by
// the same encrypted /settings/api-keys store as broker keys (service="anthropic").
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Sparkles, Trash2, Plus, ExternalLink } from "lucide-react";
import {
  createApiCredential,
  deleteApiCredential,
  listApiCredentials,
  type ApiCredential,
} from "@/lib/api/settings";

const QK = ["apiCredentials"];

export function AnthropicKeyCard() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: QK, queryFn: listApiCredentials });
  const [apiKey, setApiKey] = useState("");

  const keys = (data ?? []).filter((c) => c.service === "anthropic");
  const connected: ApiCredential | undefined = keys[0];

  const create = useMutation({
    mutationFn: () =>
      createApiCredential({
        service: "anthropic",
        label: "Anthropic API key",
        payload: { api_key: apiKey.trim() },
      }),
    onSuccess: () => {
      toast.success("AI copilot key connected");
      setApiKey("");
      qc.invalidateQueries({ queryKey: QK });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Could not save key"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteApiCredential(id),
    onSuccess: () => {
      toast("AI copilot key removed");
      qc.invalidateQueries({ queryKey: QK });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Could not remove key"),
  });

  return (
    <Card className="border-border bg-elevated p-5">
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-violet" />
        <h2 className="font-semibold">AI copilot key</h2>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        The copilot, strategy builder, and AI analysis run on <strong>your own</strong>{" "}
        Anthropic key — your AI usage bills to your account. Get one at{" "}
        <a
          href="https://console.anthropic.com/settings/keys"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-0.5 text-violet hover:underline"
        >
          console.anthropic.com <ExternalLink className="size-3" />
        </a>
        . Stored encrypted; only the last 4 characters are ever shown.
      </p>
      <Separator className="my-4" />

      {error ? (
        <p className="text-sm text-destructive">Couldn't load your key. {(error as Error).message}</p>
      ) : isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : connected ? (
        <div className="flex items-center justify-between rounded-md border border-border bg-background/40 px-3 py-2">
          <div className="min-w-0">
            <div className="text-sm font-medium">Anthropic key connected</div>
            <div className="text-xs text-muted-foreground">
              {connected.last_four ? `••••${connected.last_four}` : "••••"} · added{" "}
              {new Date(connected.created_at).toLocaleDateString()}
            </div>
          </div>
          <Button
            size="icon"
            variant="ghost"
            disabled={remove.isPending}
            onClick={() => remove.mutate(connected.id)}
            aria-label="Remove AI copilot key"
          >
            <Trash2 className="size-4 text-muted-foreground" />
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Anthropic API key</Label>
            <Input
              className="bg-background font-mono"
              type="password"
              autoComplete="off"
              placeholder="sk-ant-…"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>
          <Button
            disabled={!apiKey.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            <Plus className="mr-1 size-4" />
            {create.isPending ? "Connecting…" : "Connect key"}
          </Button>
        </div>
      )}
    </Card>
  );
}

export default AnthropicKeyCard;
