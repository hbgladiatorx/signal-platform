"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { AppShell } from "@/components/nav/AppShell";
import type { Strategy } from "@/lib/backtest-types";
import { useApi } from "@/lib/useApi";

// Strategy type extended with the source field from Step 27's merged endpoint
interface StrategyWithSource extends Strategy {
  source: "built-in" | "user";
  user_strategy_id?: string | null;
}

export default function StrategiesPage() {
  const api = useApi();

  const { data, isLoading, error } = useQuery({
    queryKey: ["strategies"],
    queryFn: () => api.get<StrategyWithSource[]>("/strategies"),
  });

  return (
    <AppShell title="Strategies">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-navy-700">
              Available strategies
            </h2>
            <p className="mt-1 text-xs text-gray-500">
              Built-in strategies plus the ones you&rsquo;ve authored.
              Create new strategies in plain English; run backtests from the{" "}
              <Link
                href="/backtests/new"
                className="text-navy-600 hover:underline"
              >
                new backtest
              </Link>{" "}
              page.
            </p>
          </div>
          <div className="flex gap-2">
            <Link
              href="/strategies/new"
              className="rounded-md border border-navy-600 bg-white px-4 py-2 text-sm font-medium text-navy-700 hover:bg-navy-50"
            >
              + New strategy
            </Link>
            <Link
              href="/backtests/new"
              className="rounded-md bg-navy-600 px-4 py-2 text-sm font-medium text-white hover:bg-navy-700"
            >
              New backtest
            </Link>
          </div>
        </div>

        {isLoading && (
          <div className="rounded-lg border border-gray-200 bg-white px-6 py-12 text-center text-sm text-gray-500">
            Loading strategies…
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
            Failed to load strategies: {(error as Error).message}
          </div>
        )}

        {data && data.length === 0 && (
          <div className="rounded-lg border border-gray-200 bg-white px-6 py-12 text-center text-sm text-gray-500">
            No strategies yet.{" "}
            <Link
              href="/strategies/new"
              className="text-navy-600 hover:underline"
            >
              Create your first strategy
            </Link>
            .
          </div>
        )}

        {data && data.length > 0 && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {data.map((strategy) => (
              <StrategyCard
                key={`${strategy.source}-${strategy.name}`}
                strategy={strategy}
              />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}

function StrategyCard({ strategy }: { strategy: StrategyWithSource }) {
  const api = useApi();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  // Only user-authored strategies are deletable; built-ins are code on disk.
  const isDeletable =
    strategy.source === "user" && Boolean(strategy.user_strategy_id);

  const deleteMutation = useMutation({
    mutationFn: () =>
      api.delete<void>(`/user-strategies/${strategy.user_strategy_id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategies"] });
      setConfirming(false);
    },
  });

  const paramKeys = Object.keys(strategy.params_schema.properties ?? {});

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-mono text-sm font-semibold text-navy-700">
            {strategy.name}
          </h3>
          <SourceBadge source={strategy.source} />
        </div>
        {strategy.description && (
          <p className="mt-1 text-sm text-gray-600">{strategy.description}</p>
        )}
      </div>

      <div className="px-6 py-4">
        <p className="mb-2 text-xs uppercase tracking-wide text-gray-500">
          Parameters ({paramKeys.length})
        </p>
        <dl className="space-y-2 text-sm">
          {paramKeys.map((key) => {
            const param = strategy.params_schema.properties[key];
            return (
              <div
                key={key}
                className="flex items-center justify-between gap-3 border-b border-gray-100 pb-2 last:border-0 last:pb-0"
              >
                <div className="flex-1">
                  <span className="font-mono text-xs text-navy-600">
                    {key}
                  </span>
                  {param.description && (
                    <p className="mt-0.5 text-xs text-gray-500">
                      {param.description}
                    </p>
                  )}
                </div>
                <div className="text-right text-xs text-gray-600">
                  <div>
                    <span className="text-gray-400">type:</span> {param.type}
                  </div>
                  {param.default !== undefined && (
                    <div>
                      <span className="text-gray-400">default:</span>{" "}
                      {String(param.default)}
                    </div>
                  )}
                  {(param.minimum !== undefined ||
                    param.maximum !== undefined) && (
                    <div className="text-gray-400">
                      [
                      {param.minimum !== undefined ? param.minimum : ""}
                      {(param.minimum !== undefined ||
                        param.maximum !== undefined) && ","}
                      {param.maximum !== undefined ? param.maximum : ""}
                      ]
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </dl>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-gray-200 bg-gray-50 px-6 py-3">
        <div className="min-h-[1.25rem]">
          {isDeletable &&
            (deleteMutation.isError ? (
              <span className="inline-flex items-center gap-2">
                <span className="text-xs text-red-600">
                  Failed to delete
                </span>
                <button
                  type="button"
                  onClick={() => deleteMutation.mutate()}
                  className="text-xs font-medium text-red-600 hover:text-red-700"
                >
                  Retry
                </button>
                <button
                  type="button"
                  onClick={() => {
                    deleteMutation.reset();
                    setConfirming(false);
                  }}
                  className="text-xs text-gray-500 hover:text-gray-700"
                >
                  Cancel
                </button>
              </span>
            ) : confirming ? (
              <span className="inline-flex items-center gap-2">
                <span className="text-xs text-gray-500">Delete this strategy?</span>
                <button
                  type="button"
                  onClick={() => deleteMutation.mutate()}
                  disabled={deleteMutation.isPending}
                  className="text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
                >
                  {deleteMutation.isPending ? "Deleting…" : "Delete"}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  disabled={deleteMutation.isPending}
                  className="text-xs text-gray-500 hover:text-gray-700"
                >
                  Cancel
                </button>
              </span>
            ) : (
              <span className="inline-flex items-center gap-3">
                <Link
                  href={`/strategies/${strategy.user_strategy_id}/edit`}
                  className="text-xs text-gray-500 hover:text-navy-600"
                >
                  Edit
                </Link>
                <button
                  type="button"
                  onClick={() => setConfirming(true)}
                  className="text-xs text-gray-500 hover:text-red-600"
                >
                  Delete
                </button>
              </span>
            ))}
        </div>
        <Link
          href={`/backtests/new?strategy=${encodeURIComponent(strategy.name)}`}
          className="text-sm font-medium text-navy-600 hover:underline"
        >
          Backtest this →
        </Link>
      </div>
    </div>
  );
}

function SourceBadge({ source }: { source: "built-in" | "user" }) {
  const styles =
    source === "built-in"
      ? "bg-gray-100 text-gray-700"
      : "bg-blue-50 text-blue-700";
  const label = source === "built-in" ? "built-in" : "yours";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs ${styles}`}>
      {label}
    </span>
  );
}
