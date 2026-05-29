"use client";

// frontend/app/walkforwards/new/page.tsx
// Form to create a new walk-forward analysis: strategy + symbol +
// param grid + windowing config + selection metric.

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import {
  CreateWalkforwardRequest,
  SelectionMetric,
  SELECTION_METRICS,
  BAR_RESOLUTIONS,
} from "@/lib/walkforward-types";
import { fetchAuthed, API_BASE } from "@/lib/api";

interface ParamRow {
  key: string;
  values: string; // comma-separated raw input
}

const MAX_COMBOS = 200; // walk-forward × combos can balloon; keep room
const DEFAULT_BAR_RESOLUTION = "1d";

export default function NewWalkforwardPage() {
  const router = useRouter();

  // --- Strategy list (built-ins; user strategies are picked up server-side) ---
  const [strategies, setStrategies] = useState<string[] | null>(null);
  const [strategyName, setStrategyName] = useState<string>("");

  // --- Symbol list ---
  const [allSymbols, setAllSymbols] = useState<string[] | null>(null);
  const [symbol, setSymbol] = useState<string>("");

  // --- Configurable fields ---
  const [barResolution, setBarResolution] =
    useState<string>(DEFAULT_BAR_RESOLUTION);
  const [startingCash, setStartingCash] = useState<number>(10000);
  const [feeRateBps, setFeeRateBps] = useState<number>(10);
  const [slippageBps, setSlippageBps] = useState<number>(5);

  // --- Param grid ---
  const [paramRows, setParamRows] = useState<ParamRow[]>([
    { key: "slow_period", values: "30, 50, 100, 150" },
  ]);

  // --- Windowing ---
  const [trainBars, setTrainBars] = useState<number>(180);
  const [testBars, setTestBars] = useState<number>(30);
  const [numWindows, setNumWindows] = useState<number>(5);
  const [selectionMetric, setSelectionMetric] =
    useState<SelectionMetric>("sharpe");

  // --- Submit state ---
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load strategies and symbols on mount
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [stratRes, instrRes] = await Promise.all([
          fetchAuthed(`${API_BASE}/strategies`),
          fetchAuthed(`${API_BASE}/instruments`),
        ]);
        if (stratRes.ok) {
          const data = await stratRes.json();
          if (alive) {
            const names = Array.isArray(data)
              ? data.map((s: { name?: string } | string) =>
                  typeof s === "string" ? s : (s.name ?? ""),
                ).filter(Boolean)
              : [];
            setStrategies(names);
            if (names.length > 0) setStrategyName(names[0]);
          }
        }
        if (instrRes.ok) {
          const data = await instrRes.json();
          if (alive) {
            const syms = Array.isArray(data)
              ? data
                  .map(
                    (i: { canonical_symbol?: string; active?: boolean }) =>
                      i.canonical_symbol ?? "",
                  )
                  .filter(Boolean)
              : [];
            setAllSymbols(syms);
            if (syms.length > 0 && !symbol) setSymbol(syms[0]);
          }
        }
      } catch (e) {
        if (alive)
          setError(
            `Failed to load strategies/instruments: ${e instanceof Error ? e.message : "error"}`,
          );
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Parse a comma-separated values string into typed values
  function parseValues(raw: string): unknown[] {
    return raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => {
        const n = Number(s);
        if (!Number.isNaN(n) && /^-?\d+(\.\d+)?$/.test(s)) return n;
        if (s === "true") return true;
        if (s === "false") return false;
        return s;
      });
  }

  const paramGrid = useMemo(() => {
    const out: Record<string, unknown[]> = {};
    for (const row of paramRows) {
      if (!row.key.trim()) continue;
      const vals = parseValues(row.values);
      if (vals.length > 0) out[row.key.trim()] = vals;
    }
    return out;
  }, [paramRows]);

  const numCombos = useMemo(() => {
    const values = Object.values(paramGrid);
    if (values.length === 0) return 1;
    return values.reduce((acc, arr) => acc * arr.length, 1);
  }, [paramGrid]);

  const totalBacktests = numCombos * numWindows + numWindows;

  function addParamRow() {
    setParamRows([...paramRows, { key: "", values: "" }]);
  }

  function removeParamRow(idx: number) {
    setParamRows(paramRows.filter((_, i) => i !== idx));
  }

  function updateParamRow(idx: number, patch: Partial<ParamRow>) {
    setParamRows(paramRows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  }

  const canSubmit =
    strategyName &&
    symbol &&
    barResolution &&
    trainBars > 0 &&
    testBars > 0 &&
    numWindows > 0 &&
    Object.keys(paramGrid).length > 0 &&
    numCombos <= MAX_COMBOS &&
    !submitting;

  async function submit() {
    setSubmitting(true);
    setError(null);

    const req: CreateWalkforwardRequest = {
      strategy_name: strategyName,
      symbols: [symbol],
      bar_resolution: barResolution,
      starting_cash: startingCash,
      fee_rate_bps: feeRateBps,
      slippage_bps: slippageBps,
      param_grid: paramGrid,
      train_bars: trainBars,
      test_bars: testBars,
      num_windows: numWindows,
      selection_metric: selectionMetric,
    };

    try {
      const res = await fetchAuthed(`${API_BASE}/walkforwards`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`HTTP ${res.status}: ${text}`);
      }
      const created = await res.json();
      router.push(`/walkforwards/${created.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      setSubmitting(false);
    }
  }

  return (
    <div className="container mx-auto p-6 max-w-4xl">
      <div className="mb-6">
        <Link
          href="/walkforwards"
          className="text-sm text-indigo-600 hover:underline"
        >
          ← Walk-Forwards
        </Link>
        <h1 className="text-2xl font-bold text-gray-900 mt-2">
          New Walk-Forward Analysis
        </h1>
        <p className="text-sm text-gray-600 mt-1">
          Sweep your parameter grid on a rolling training window, then test the
          best params on the next (held-out) segment. Repeated{" "}
          <em>N</em> times to estimate honest out-of-sample performance.
        </p>
      </div>

      <div className="space-y-6">
        {/* Card 1: Strategy + symbol */}
        <section className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            Strategy & Symbol
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Strategy
              </label>
              <select
                value={strategyName}
                onChange={(e) => setStrategyName(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              >
                {strategies === null && <option>Loading…</option>}
                {strategies?.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Symbol
              </label>
              <select
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              >
                {allSymbols === null && <option>Loading…</option>}
                {allSymbols?.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Bar Resolution
              </label>
              <select
                value={barResolution}
                onChange={(e) => setBarResolution(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              >
                {BAR_RESOLUTIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Starting Cash (USD)
              </label>
              <input
                type="number"
                value={startingCash}
                min={100}
                onChange={(e) => setStartingCash(Number(e.target.value))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Fee (bps)
              </label>
              <input
                type="number"
                value={feeRateBps}
                min={0}
                max={1000}
                onChange={(e) => setFeeRateBps(Number(e.target.value))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Slippage (bps)
              </label>
              <input
                type="number"
                value={slippageBps}
                min={0}
                max={1000}
                onChange={(e) => setSlippageBps(Number(e.target.value))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>
          </div>
        </section>

        {/* Card 2: Param grid */}
        <section className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-base font-semibold text-gray-900">
              Parameter Grid
            </h2>
            <span className="text-xs text-gray-500">
              Cartesian product across each row's values.
            </span>
          </div>

          <div className="space-y-2">
            {paramRows.map((row, idx) => (
              <div key={idx} className="flex gap-2 items-start">
                <input
                  type="text"
                  placeholder="param name (e.g. slow_period)"
                  value={row.key}
                  onChange={(e) =>
                    updateParamRow(idx, { key: e.target.value })
                  }
                  className="flex-1 max-w-[200px] px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 font-mono"
                />
                <input
                  type="text"
                  placeholder="comma-separated values (e.g. 30, 50, 100)"
                  value={row.values}
                  onChange={(e) =>
                    updateParamRow(idx, { values: e.target.value })
                  }
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 font-mono"
                />
                <button
                  type="button"
                  onClick={() => removeParamRow(idx)}
                  className="px-3 py-2 text-sm text-gray-500 hover:text-red-600"
                  aria-label="Remove parameter row"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>

          <button
            type="button"
            onClick={addParamRow}
            className="mt-3 text-sm text-indigo-600 hover:underline"
          >
            + Add parameter
          </button>

          <div className="mt-4 flex items-center gap-4 text-sm">
            <div className="text-gray-700">
              Combos:{" "}
              <span className="font-medium tabular-nums">{numCombos}</span>
            </div>
            <div className="text-gray-700">
              Total backtests:{" "}
              <span className="font-medium tabular-nums">
                {totalBacktests}
              </span>{" "}
              <span className="text-xs text-gray-500">
                ({numCombos} × {numWindows} train + {numWindows} test)
              </span>
            </div>
          </div>
          {numCombos > MAX_COMBOS && (
            <div className="mt-3 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-md p-2">
              Param combos ({numCombos}) exceeds MAX_COMBOS ({MAX_COMBOS}).
              Reduce the grid before submitting.
            </div>
          )}
        </section>

        {/* Card 3: Windowing */}
        <section className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <h2 className="text-base font-semibold text-gray-900 mb-3">
            Walk-Forward Windowing
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Train Bars
              </label>
              <input
                type="number"
                value={trainBars}
                min={10}
                onChange={(e) => setTrainBars(Number(e.target.value))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-xs text-gray-500 mt-1">
                Bars used to optimize params.
              </p>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Test Bars
              </label>
              <input
                type="number"
                value={testBars}
                min={5}
                onChange={(e) => setTestBars(Number(e.target.value))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-xs text-gray-500 mt-1">
                Held-out bars per window.
              </p>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                # Windows
              </label>
              <input
                type="number"
                value={numWindows}
                min={1}
                max={50}
                onChange={(e) => setNumWindows(Number(e.target.value))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-xs text-gray-500 mt-1">
                Rolling steps (more = more signal).
              </p>
            </div>
            <div className="md:col-span-3">
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Selection Metric
              </label>
              <select
                value={selectionMetric}
                onChange={(e) =>
                  setSelectionMetric(e.target.value as SelectionMetric)
                }
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-indigo-500"
              >
                {SELECTION_METRICS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label} — {m.description}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="mt-3 text-xs text-gray-500">
            Data required: at least{" "}
            <span className="font-medium tabular-nums">
              {trainBars + testBars * numWindows}
            </span>{" "}
            bars at <span className="font-mono">{barResolution}</span>.
          </div>
        </section>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-800 p-4 rounded-md text-sm">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Link
            href="/walkforwards"
            className="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Cancel
          </Link>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {submitting ? "Submitting…" : "Run Walk-Forward"}
          </button>
        </div>

        <div className="text-xs text-gray-500 leading-relaxed">
          <strong className="text-gray-700">Educational use only.</strong>{" "}
          Walk-forward results are diagnostic, not predictive. Past performance
          on held-out historical windows does not predict future returns.
          Trading involves substantial risk; you may lose your entire
          investment.
        </div>
      </div>
    </div>
  );
}
