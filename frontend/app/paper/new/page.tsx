"use client";

// frontend/app/paper/new/page.tsx
// Create + start a live paper-trading session.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import type { Strategy } from "@/lib/backtest-types";
import {
  ApiCredential,
  ASSET_CLASSES,
  BAR_RESOLUTIONS,
  CreatePaperSessionRequest,
  PaperAssetClass,
} from "@/lib/paper-types";

const inputCls =
  "w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500";

export default function NewPaperSessionPage() {
  const api = useApi();
  const router = useRouter();

  const stratQuery = useQuery({
    queryKey: ["strategies"],
    queryFn: () => api.get<Strategy[]>("/strategies"),
  });
  const instrQuery = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<unknown[]>("/instruments"),
  });
  const credQuery = useQuery({
    queryKey: ["api-keys"],
    queryFn: () => api.get<ApiCredential[]>("/settings/api-keys"),
  });

  // Both venues can place trades: Alpaca (paper) and Binance.US (LIVE money).
  const tradingKeys = useMemo(
    () =>
      (credQuery.data ?? []).filter(
        (c) => c.service === "alpaca" || c.service === "binanceus",
      ),
    [credQuery.data],
  );
  const instrumentSymbols = useMemo(
    () =>
      (instrQuery.data ?? [])
        .map((i) => (i as { canonical_symbol?: string }).canonical_symbol ?? "")
        .filter(Boolean) as string[],
    [instrQuery.data],
  );

  // Form state
  const [strategyName, setStrategyName] = useState("");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [assetClass, setAssetClass] = useState<PaperAssetClass>("crypto_spot");
  const [symbolsText, setSymbolsText] = useState("");
  const [barResolution, setBarResolution] = useState("1m");
  const [credentialId, setCredentialId] = useState("");
  const [startingCash, setStartingCash] = useState(100000);
  const [maxNotional, setMaxNotional] = useState<number | "">("");
  const [maxDailyLoss, setMaxDailyLoss] = useState<number | "">("");
  const [confirmLive, setConfirmLive] = useState(false);
  const [cancelOnStop, setCancelOnStop] = useState(true);

  const selectedCred = useMemo(
    () => tradingKeys.find((c) => c.id === credentialId),
    [tradingKeys, credentialId],
  );
  // Binance.US trades real money; Alpaca is paper.
  const isLive = selectedCred?.service === "binanceus";

  const selectedStrategy = useMemo(
    () => stratQuery.data?.find((s) => s.name === strategyName),
    [stratQuery.data, strategyName],
  );

  // Defaults once data lands.
  useEffect(() => {
    if (stratQuery.data?.length && !strategyName) {
      setStrategyName(stratQuery.data[0].name);
    }
  }, [stratQuery.data, strategyName]);
  useEffect(() => {
    if (tradingKeys.length && !credentialId) setCredentialId(tradingKeys[0].id);
  }, [tradingKeys, credentialId]);

  // Reset the live confirmation whenever the venue changes.
  useEffect(() => {
    setConfirmLive(false);
  }, [credentialId]);

  // Seed param defaults from the selected strategy's schema.
  useEffect(() => {
    if (!selectedStrategy) return;
    const props = selectedStrategy.params_schema?.properties ?? {};
    const seed: Record<string, unknown> = {};
    for (const [key, spec] of Object.entries(props)) {
      seed[key] = spec.default ?? (spec.type === "boolean" ? false : "");
    }
    setParams(seed);
  }, [selectedStrategy]);

  const symbols = useMemo(
    () =>
      symbolsText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    [symbolsText],
  );

  const createMutation = useMutation({
    mutationFn: (req: CreatePaperSessionRequest) =>
      api.post<{ id: string }>("/paper-sessions", req),
    onSuccess: (data) => router.push(`/paper/${data.id}`),
  });

  // Live sessions REQUIRE a daily-loss limit and an explicit confirmation.
  const liveReady =
    !isLive || (maxDailyLoss !== "" && Number(maxDailyLoss) > 0 && confirmLive);

  const canSubmit = Boolean(
    strategyName &&
      symbols.length > 0 &&
      credentialId &&
      startingCash > 0 &&
      liveReady &&
      !createMutation.isPending,
  );

  function submit() {
    if (!canSubmit) return;
    createMutation.mutate({
      strategy_name: strategyName,
      params,
      symbols,
      asset_class: assetClass,
      bar_resolution: barResolution,
      api_credential_id: credentialId,
      starting_cash: startingCash,
      max_order_notional: maxNotional === "" ? null : Number(maxNotional),
      max_daily_loss:
        isLive && maxDailyLoss !== "" ? Number(maxDailyLoss) : null,
      cancel_open_on_stop: cancelOnStop,
    });
  }

  const paramProps = selectedStrategy?.params_schema?.properties ?? {};

  return (
    <AppShell title="New Paper Session">
      <div className="space-y-4 max-w-4xl">
        <div>
          <Link href="/paper" className="text-sm text-indigo-600 hover:underline">
            ← Paper Trading
          </Link>
          <h2 className="text-base font-semibold text-navy-700 mt-2">
            Start a live paper-trading session
          </h2>
          <p className="mt-1 text-xs text-gray-500 max-w-2xl">
            The runner advances your strategy on each closed bar and submits
            orders to your Alpaca paper account. Stop it any time.
          </p>
        </div>

        {tradingKeys.length === 0 && !credQuery.isLoading && (
          <div className="bg-amber-50 border border-amber-200 text-amber-800 p-4 rounded-md text-sm">
            No trading API key found.{" "}
            <Link href="/settings" className="underline">
              Add one in Settings
            </Link>{" "}
            — Alpaca (paper) or Binance.US (live) — before starting a session.
          </div>
        )}

        {isLive && (
          <div className="bg-red-50 border-2 border-red-400 text-red-900 p-4 rounded-md text-sm">
            <strong className="block text-red-800 mb-1">
              ⚠ LIVE TRADING — REAL MONEY
            </strong>
            This session routes orders to your <strong>Binance.US</strong>{" "}
            account and trades real funds. Binance.US has no paper sandbox. A
            daily-loss limit is required, and the global kill-switch on the Paper
            Trading page can halt all live submission at any time.
          </div>
        )}

        {/* Strategy + symbols */}
        <section className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-navy-700 mb-4">Strategy &amp; Market</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Strategy</label>
              <select value={strategyName} onChange={(e) => setStrategyName(e.target.value)} className={inputCls}>
                {!stratQuery.data && <option>Loading…</option>}
                {stratQuery.data?.map((s) => (
                  <option key={s.name} value={s.name}>{s.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Asset Class</label>
              <select value={assetClass} onChange={(e) => setAssetClass(e.target.value as PaperAssetClass)} className={inputCls}>
                {ASSET_CLASSES.map((a) => (
                  <option key={a.value} value={a.value}>{a.label}</option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-1">
                {ASSET_CLASSES.find((a) => a.value === assetClass)?.hint}
              </p>
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Symbols (comma-separated canonical symbols)
              </label>
              <input
                type="text"
                list="instrument-symbols"
                value={symbolsText}
                onChange={(e) => setSymbolsText(e.target.value)}
                placeholder="BTC-USDT@BINANCEUS, ETH-USDT@BINANCEUS"
                className={`${inputCls} font-mono`}
              />
              <datalist id="instrument-symbols">
                {instrumentSymbols.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
              {symbols.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {symbols.map((s) => (
                    <span key={s} className="px-2 py-0.5 bg-gray-100 border border-gray-200 rounded text-xs font-mono">{s}</span>
                  ))}
                </div>
              )}
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Bar Resolution</label>
              <select value={barResolution} onChange={(e) => setBarResolution(e.target.value)} className={inputCls}>
                {BAR_RESOLUTIONS.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Trading Account</label>
              <select value={credentialId} onChange={(e) => setCredentialId(e.target.value)} className={inputCls}>
                {tradingKeys.length === 0 && <option value="">No trading key</option>}
                {tradingKeys.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.service === "binanceus" ? "Binance.US LIVE" : "Alpaca paper"}
                    {" · "}
                    {c.label}
                    {c.last_four ? ` (…${c.last_four})` : ""}
                  </option>
                ))}
              </select>
              <p className={`text-xs mt-1 ${isLive ? "text-red-700 font-medium" : "text-gray-500"}`}>
                {isLive
                  ? "Real money — orders execute on Binance.US."
                  : "Simulated — orders route to Alpaca's paper endpoint."}
              </p>
            </div>
          </div>
        </section>

        {/* Strategy params */}
        {Object.keys(paramProps).length > 0 && (
          <section className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-navy-700 mb-4">Strategy Parameters</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {Object.entries(paramProps).map(([key, spec]) => (
                <div key={key}>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    {spec.title ?? key}
                  </label>
                  {spec.type === "boolean" ? (
                    <input
                      type="checkbox"
                      checked={Boolean(params[key])}
                      onChange={(e) => setParams((p) => ({ ...p, [key]: e.target.checked }))}
                      className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                    />
                  ) : (
                    <input
                      type={spec.type === "string" ? "text" : "number"}
                      value={(params[key] as string | number) ?? ""}
                      min={spec.minimum}
                      max={spec.maximum}
                      onChange={(e) => {
                        const raw = e.target.value;
                        const val =
                          spec.type === "string"
                            ? raw
                            : raw === ""
                              ? ""
                              : Number(raw);
                        setParams((p) => ({ ...p, [key]: val }));
                      }}
                      className={inputCls}
                    />
                  )}
                  {spec.description && (
                    <p className="text-xs text-gray-500 mt-1">{spec.description}</p>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Risk / account */}
        <section className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-navy-700 mb-4">Account &amp; Guardrails</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Starting Cash (reference)</label>
              <input type="number" value={startingCash} min={100} onChange={(e) => setStartingCash(Number(e.target.value))} className={inputCls} />
              <p className="text-xs text-gray-500 mt-1">Informational; actual balance comes from Alpaca.</p>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Max Order Notional (USD)</label>
              <input
                type="number"
                value={maxNotional}
                min={0}
                placeholder="unlimited"
                onChange={(e) => setMaxNotional(e.target.value === "" ? "" : Number(e.target.value))}
                className={inputCls}
              />
              <p className="text-xs text-gray-500 mt-1">Reject any single order above this notional.</p>
            </div>
            <div className="flex items-center gap-2 pt-6">
              <input
                id="cancelOnStop"
                type="checkbox"
                checked={cancelOnStop}
                onChange={(e) => setCancelOnStop(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
              />
              <label htmlFor="cancelOnStop" className="text-sm text-gray-700">
                Cancel open orders on stop
              </label>
            </div>
          </div>

          {isLive && (
            <div className="mt-4 border-t border-gray-200 pt-4 space-y-3">
              <div className="max-w-xs">
                <label className="block text-xs font-medium text-red-800 mb-1">
                  Max Daily Loss (USD) — required
                </label>
                <input
                  type="number"
                  value={maxDailyLoss}
                  min={1}
                  placeholder="e.g. 250"
                  onChange={(e) =>
                    setMaxDailyLoss(e.target.value === "" ? "" : Number(e.target.value))
                  }
                  className={`${inputCls} ${maxDailyLoss === "" ? "border-red-300" : ""}`}
                />
                <p className="text-xs text-gray-500 mt-1">
                  Auto-halt this session if intraday equity drawdown exceeds this.
                </p>
              </div>
              <div className="flex items-start gap-2">
                <input
                  id="confirmLive"
                  type="checkbox"
                  checked={confirmLive}
                  onChange={(e) => setConfirmLive(e.target.checked)}
                  className="h-4 w-4 mt-0.5 rounded border-gray-300 text-red-600 focus:ring-red-500"
                />
                <label htmlFor="confirmLive" className="text-sm text-red-900">
                  I understand this trades <strong>real money</strong> on
                  Binance.US and accept the risk.
                </label>
              </div>
            </div>
          )}
        </section>

        {createMutation.isError && (
          <div className="bg-red-50 border border-red-200 text-red-800 p-4 rounded-md text-sm">
            {(createMutation.error as Error).message}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Link href="/paper" className="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50">
            Cancel
          </Link>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className={`px-4 py-2 text-sm font-medium text-white rounded-md disabled:bg-gray-300 disabled:cursor-not-allowed ${
              isLive
                ? "bg-red-600 hover:bg-red-700"
                : "bg-indigo-600 hover:bg-indigo-700"
            }`}
          >
            {createMutation.isPending
              ? "Starting…"
              : isLive
                ? "Start LIVE Session"
                : "Start Session"}
          </button>
        </div>

        <div className="text-xs text-gray-500 leading-relaxed pt-2">
          <strong className="text-gray-700">Paper trading only.</strong> Orders go
          to Alpaca&apos;s paper endpoint. Crypto signals use Binance.US bars while
          fills happen at Alpaca prices, so executions won&apos;t match bar closes
          exactly. Educational use only — not investment advice.
        </div>
      </div>
    </AppShell>
  );
}
