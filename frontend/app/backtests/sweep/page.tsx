"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { AppShell } from "@/components/nav/AppShell";
import type { BacktestStatus, BacktestSummary } from "@/lib/backtest-types";
import { useApi } from "@/lib/useApi";

// Cap on combinations per sweep — guardrail against runaway grids.
const MAX_COMBOS = 50;

interface ParamRow {
  name: string;
  values: number[];
}

interface SweepEntry {
  combo: Record<string, number>;
  id: string | null;
  error?: string;
}

// ----------------- grid parsing -----------------
// Each line: "param_name: 5, 10, 20" → ParamRow { name, values: [5,10,20] }
// Blank lines and lines starting with # are ignored.
function parseGrid(text: string): { rows: ParamRow[]; errors: string[] } {
  const rows: ParamRow[] = [];
  const errors: string[] = [];
  const seen = new Set<string>();
  text.split("\n").forEach((line, i) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) return;
    const colonIdx = trimmed.indexOf(":");
    if (colonIdx < 0) {
      errors.push(`Line ${i + 1}: missing ":" — expected "name: a, b, c"`);
      return;
    }
    const name = trimmed.slice(0, colonIdx).trim();
    if (!name) {
      errors.push(`Line ${i + 1}: empty parameter name`);
      return;
    }
    if (seen.has(name)) {
      errors.push(`Line ${i + 1}: duplicate parameter "${name}"`);
      return;
    }
    seen.add(name);
    const values: number[] = [];
    for (const v of trimmed.slice(colonIdx + 1).split(",")) {
      const t = v.trim();
      if (!t) continue;
      const n = Number(t);
      if (Number.isNaN(n)) {
        errors.push(`Line ${i + 1}: "${t}" is not a number`);
        return;
      }
      values.push(n);
    }
    if (values.length === 0) {
      errors.push(`Line ${i + 1}: no values`);
      return;
    }
    rows.push({ name, values });
  });
  return { rows, errors };
}

function cartesianProduct(params: ParamRow[]): Record<string, number>[] {
  if (params.length === 0) return [];
  let result: Record<string, number>[] = [{}];
  for (const p of params) {
    const next: Record<string, number>[] = [];
    for (const r of result) {
      for (const v of p.values) {
        next.push({ ...r, [p.name]: v });
      }
    }
    result = next;
  }
  return result;
}

const RESOLUTIONS = ["1m", "5m", "15m", "1h", "4h", "1d"];

// ============================================================
// Page
// ============================================================
export default function SweepPage() {
  const api = useApi();

  // ---- form state ----
  const [strategyName, setStrategyName] = useState("SMACrossover");
  const [symbol, setSymbol] = useState("BTC-USDT@BINANCEUS");
  const [resolution, setResolution] = useState("1d");
  const [startingCash, setStartingCash] = useState("10000");
  const [feeBps, setFeeBps] = useState("10");
  const [slippageBps, setSlippageBps] = useState("5");
  const [gridText, setGridText] = useState(
    "fast_window: 5, 10, 20\nslow_window: 50, 100, 200"
  );

  // ---- submission state ----
  const [entries, setEntries] = useState<SweepEntry[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // ---- strategy + instrument lists ----
  const { data: strategies } = useQuery({
    queryKey: ["sweep-strategies"],
    queryFn: async () => {
      const builtIn = await api
        .get<{ name: string }[]>("/strategies")
        .catch(() => [] as { name: string }[]);
      const user = await api
        .get<{ name: string }[]>("/user-strategies")
        .catch(() => [] as { name: string }[]);
      const names = new Set<string>();
      [...builtIn, ...user].forEach((s) => names.add(s.name));
      return Array.from(names).sort();
    },
  });

  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () =>
      api
        .get<{ canonical_symbol: string; active: boolean }[]>("/instruments")
        .catch(() => [] as { canonical_symbol: string; active: boolean }[]),
  });

  // ---- parsed grid ----
  const { rows: parsedRows, errors: parseErrors } = useMemo(
    () => parseGrid(gridText),
    [gridText]
  );
  const combos = useMemo(() => cartesianProduct(parsedRows), [parsedRows]);

  // ---- submit handler ----
  const handleSubmit = async () => {
    if (submitting) return;
    if (parseErrors.length > 0) {
      setSubmitError("Fix grid errors first.");
      return;
    }
    if (combos.length === 0) {
      setSubmitError("Grid is empty.");
      return;
    }
    if (combos.length > MAX_COMBOS) {
      setSubmitError(
        `Refusing to run ${combos.length} backtests (max ${MAX_COMBOS}).`
      );
      return;
    }
    setSubmitError(null);
    setSubmitting(true);

    const cashNum = parseFloat(startingCash);
    const feeNum = parseInt(feeBps, 10);
    const slipNum = parseInt(slippageBps, 10);

    const promises = combos.map(async (combo) => {
      try {
        const resp = await api.post<{ id: string }>("/backtests", {
          strategy_name: strategyName,
          symbols: [symbol],
          bar_resolution: resolution,
          params: combo,
          starting_cash: cashNum,
          fee_rate_bps: feeNum,
          slippage_bps: slipNum,
        });
        return { combo, id: resp.id };
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return { combo, id: null, error: msg || "submit failed" } as SweepEntry;
      }
    });
    const results = await Promise.all(promises);
    setEntries(results);
    setSubmitting(false);
  };

  // ---- poll all backtests once a sweep is submitted ----
  const { data: allBacktests } = useQuery({
    queryKey: ["backtests"],
    queryFn: () => api.get<BacktestSummary[]>("/backtests"),
    enabled: entries !== null,
    refetchInterval: (q) => {
      if (!entries) return false;
      const rows = q.state.data as BacktestSummary[] | undefined;
      if (!rows) return 3000;
      const stillActive = entries.some((e) => {
        if (!e.id) return false;
        const bt = rows.find((b) => b.id === e.id);
        return !bt || bt.status === "pending" || bt.status === "running";
      });
      return stillActive ? 3000 : false;
    },
  });

  // ============================================================
  // Render: form mode
  // ============================================================
  if (entries === null) {
    return (
      <AppShell title="Strategy parameter sweep">
        <div className="space-y-6 max-w-4xl">
          <div className="bg-white rounded-lg border border-slate-200 p-6 space-y-4">
            <h2 className="text-lg font-semibold">Sweep configuration</h2>
            <p className="text-sm text-slate-600">
              Run a strategy across a grid of parameter values. Each
              combination becomes a separate backtest. Results appear inline
              as each finishes.
            </p>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Strategy">
                <select
                  value={strategyName}
                  onChange={(e) => setStrategyName(e.target.value)}
                  className={inputCls}
                >
                  {(strategies ?? [strategyName]).map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </Field>
              <Field label="Symbol">
                <select
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  className={inputCls}
                >
                  {(instruments ?? [])
                    .filter((i) => i.active)
                    .map((i) => (
                      <option key={i.canonical_symbol}>
                        {i.canonical_symbol}
                      </option>
                    ))}
                  {!instruments?.some((i) => i.canonical_symbol === symbol) && (
                    <option key={symbol}>{symbol}</option>
                  )}
                </select>
              </Field>
              <Field label="Resolution">
                <select
                  value={resolution}
                  onChange={(e) => setResolution(e.target.value)}
                  className={inputCls}
                >
                  {RESOLUTIONS.map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              </Field>
              <Field label="Starting cash (USD)">
                <input
                  type="number"
                  value={startingCash}
                  onChange={(e) => setStartingCash(e.target.value)}
                  className={inputCls}
                />
              </Field>
              <Field label="Fee rate (bps)">
                <input
                  type="number"
                  value={feeBps}
                  onChange={(e) => setFeeBps(e.target.value)}
                  className={inputCls}
                />
              </Field>
              <Field label="Slippage (bps)">
                <input
                  type="number"
                  value={slippageBps}
                  onChange={(e) => setSlippageBps(e.target.value)}
                  className={inputCls}
                />
              </Field>
            </div>
          </div>

          <div className="bg-white rounded-lg border border-slate-200 p-6 space-y-4">
            <h2 className="text-lg font-semibold">Parameter grid</h2>
            <p className="text-sm text-slate-600">
              One parameter per line. Format:{" "}
              <code className="bg-slate-100 px-1 rounded text-xs">
                name: 5, 10, 20
              </code>
              . The cartesian product is run.
            </p>
            <textarea
              value={gridText}
              onChange={(e) => setGridText(e.target.value)}
              className="w-full h-32 font-mono text-sm border border-slate-300 rounded px-3 py-2"
              placeholder="fast_window: 5, 10, 20&#10;slow_window: 50, 100, 200"
            />
            {parseErrors.length > 0 && (
              <div className="text-sm text-rose-700 space-y-1">
                {parseErrors.map((e, i) => (
                  <div key={i}>• {e}</div>
                ))}
              </div>
            )}
            <div className="text-sm text-slate-700">
              <span className="font-semibold">{combos.length}</span>{" "}
              {combos.length === 1 ? "backtest" : "backtests"} will run
              {combos.length > MAX_COMBOS && (
                <span className="ml-2 text-rose-700">
                  (exceeds {MAX_COMBOS} limit)
                </span>
              )}
            </div>
          </div>

          {submitError && (
            <div className="text-sm text-rose-700">{submitError}</div>
          )}

          <div className="flex justify-end gap-2">
            <Link
              href="/backtests"
              className="px-4 py-2 text-sm text-slate-700 hover:bg-slate-100 rounded"
            >
              Cancel
            </Link>
            <button
              onClick={handleSubmit}
              disabled={
                submitting ||
                combos.length === 0 ||
                combos.length > MAX_COMBOS ||
                parseErrors.length > 0
              }
              className="px-4 py-2 text-sm bg-indigo-900 text-white rounded hover:bg-indigo-800 disabled:opacity-50"
            >
              {submitting ? "Submitting..." : `Run ${combos.length} backtests`}
            </button>
          </div>
        </div>
      </AppShell>
    );
  }

  // ============================================================
  // Render: results mode
  // ============================================================
  const paramNames = Array.from(
    new Set(entries.flatMap((e) => Object.keys(e.combo)))
  );

  const enriched = entries.map((e) => ({
    e,
    bt: e.id ? allBacktests?.find((b) => b.id === e.id) : null,
  }));
  enriched.sort((a, b) => {
    const sa = a.bt?.sharpe_ratio ?? -Infinity;
    const sb = b.bt?.sharpe_ratio ?? -Infinity;
    return sb - sa;
  });

  return (
    <AppShell title="Strategy parameter sweep">
      <div className="space-y-4 max-w-6xl">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-lg font-semibold">
              Sweep results — {entries.length} runs
            </h2>
            <p className="text-sm text-slate-600">
              {strategyName} on {symbol} @ {resolution}, sorted by Sharpe
            </p>
          </div>
          <div className="flex gap-2">
            <Link
              href="/backtests"
              className="px-3 py-1.5 text-sm border border-slate-300 rounded hover:bg-slate-50"
            >
              All backtests
            </Link>
            <button
              onClick={() => setEntries(null)}
              className="px-3 py-1.5 text-sm bg-indigo-900 text-white rounded hover:bg-indigo-800"
            >
              New sweep
            </button>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                {paramNames.map((p) => (
                  <th
                    key={p}
                    className="px-3 py-2 text-left font-medium text-slate-700 text-xs uppercase"
                  >
                    {p}
                  </th>
                ))}
                <th className="px-3 py-2 text-left font-medium text-slate-700 text-xs uppercase">
                  Status
                </th>
                <th className="px-3 py-2 text-right font-medium text-slate-700 text-xs uppercase">
                  Return
                </th>
                <th className="px-3 py-2 text-right font-medium text-slate-700 text-xs uppercase">
                  Sharpe
                </th>
                <th className="px-3 py-2 text-right font-medium text-slate-700 text-xs uppercase">
                  Max DD
                </th>
                <th className="px-3 py-2 text-right font-medium text-slate-700 text-xs uppercase">
                  Trades
                </th>
                <th className="px-3 py-2 text-right font-medium text-slate-700 text-xs uppercase">
                  Win %
                </th>
                <th className="px-3 py-2 text-right font-medium text-slate-700 text-xs uppercase">
                  Open
                </th>
              </tr>
            </thead>
            <tbody>
              {enriched.map(({ e, bt }, idx) => (
                <tr
                  key={idx}
                  className="border-b border-slate-100 hover:bg-slate-50"
                >
                  {paramNames.map((p) => (
                    <td key={p} className="px-3 py-2 font-mono text-xs">
                      {e.combo[p] ?? "—"}
                    </td>
                  ))}
                  <td className="px-3 py-2">
                    {e.error ? (
                      <span
                        className="text-rose-700 text-xs"
                        title={e.error}
                      >
                        error
                      </span>
                    ) : !bt ? (
                      <span className="text-slate-500 text-xs">pending</span>
                    ) : (
                      <StatusBadge status={bt.status} />
                    )}
                  </td>
                  <td
                    className={`px-3 py-2 font-mono text-right ${returnColor(
                      bt?.total_return_pct
                    )}`}
                  >
                    {fmtPct(bt?.total_return_pct)}
                  </td>
                  <td className="px-3 py-2 font-mono text-right">
                    {fmtNum(bt?.sharpe_ratio, 2)}
                  </td>
                  <td className="px-3 py-2 font-mono text-right">
                    {fmtPct(bt?.max_drawdown_pct)}
                  </td>
                  <td className="px-3 py-2 font-mono text-right">
                    {bt?.num_closed_trades ?? "—"}
                  </td>
                  <td className="px-3 py-2 font-mono text-right">
                    {bt?.win_rate_pct != null
                      ? bt.win_rate_pct.toFixed(1) + "%"
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {bt?.id ? (
                      <Link
                        href={`/backtests/${bt.id}`}
                        className="text-indigo-700 hover:underline text-xs"
                      >
                        detail →
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}

// ============================================================
// Helpers
// ============================================================

const inputCls =
  "w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-slate-700 uppercase tracking-wide">
        {label}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function StatusBadge({ status }: { status: BacktestStatus }) {
  const colors: Record<string, string> = {
    pending: "bg-slate-100 text-slate-700",
    running: "bg-amber-100 text-amber-800",
    completed: "bg-emerald-100 text-emerald-800",
    failed: "bg-rose-100 text-rose-800",
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 text-xs rounded ${
        colors[status] || colors.pending
      }`}
    >
      {status}
    </span>
  );
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(4) + "%";
}
function fmtNum(v: number | null | undefined, p: number = 2): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(p);
}
function returnColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return "";
  return v >= 0 ? "text-emerald-700" : "text-rose-700";
}
