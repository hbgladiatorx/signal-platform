"use client";

// frontend/app/walkforwards/new/page.tsx
// Create form for a new walk-forward analysis.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { AppShell } from "@/components/nav/AppShell";
import { useApi } from "@/lib/useApi";
import {
  CreateWalkforwardRequest,
  SelectionMetric,
  SELECTION_METRICS,
  BAR_RESOLUTIONS,
} from "@/lib/walkforward-types";

interface ParamRow {
  key: string;
  values: string;
}

const MAX_COMBOS = 200;

export default function NewWalkforwardPage() {
  const api = useApi();
  const router = useRouter();

  // Load strategy + instrument options
  const stratQuery = useQuery({
    queryKey: ["strategies"],
    queryFn: () => api.get<unknown[]>("/strategies"),
  });
  const instrQuery = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<unknown[]>("/instruments"),
  });

  const strategies = useMemo(() => {
    if (!stratQuery.data) return null;
    return stratQuery.data
      .map((s) =>
        typeof s === "string"
          ? s
          : (s as { name?: string }).name ?? "",
      )
      .filter(Boolean) as string[];
  }, [stratQuery.data]);

  const symbols = useMemo(() => {
    if (!instrQuery.data) return null;
    return instrQuery.data
      .map((i) => (i as { canonical_symbol?: string }).canonical_symbol ?? "")
      .filter(Boolean) as string[];
  }, [instrQuery.data]);

  // Form state
  const [strategyName, setStrategyName] = useState<string>("");
  const [symbol, setSymbol] = useState<string>("");
  const [barResolution, setBarResolution] = useState<string>("1d");
  const [startingCash, setStartingCash] = useState<number>(10000);
  const [feeRateBps, setFeeRateBps] = useState<number>(10);
  const [slippageBps, setSlippageBps] = useState<number>(5);
  const [paramRows, setParamRows] = useState<ParamRow[]>([
    { key: "slow_period", values: "30, 50, 100, 150" },
  ]);
  const [trainBars, setTrainBars] = useState<number>(180);
  const [testBars, setTestBars] = useState<number>(30);
  const [numWindows, setNumWindows] = useState<number>(5);
  const [selectionMetric, setSelectionMetric] =
    useState<SelectionMetric>("sharpe");

  // Default to first option once data lands
  useEffect(() => {
    if (strategies && strategies.length > 0 && !strategyName) {
      setStrategyName(strategies[0]);
    }
  }, [strategies, strategyName]);
  useEffect(() => {
    if (symbols && symbols.length > 0 && !symbol) {
      setSymbol(symbols[0]);
    }
  }, [symbols, symbol]);

  function parseValues(raw: string): unknown[] {
    return raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => {
        if (/^-?\d+(\.\d+)?$/.test(s)) {
          const n = Number(s);
          if (!Number.isNaN(n)) return n;
        }
        if (s === "true") return true;
        if (s === "false") return false;
        return s;
      });
  }

  const paramGrid = useMemo(() => {
    const out: Record<string, unknown[]> = {};
    for (const row of paramRows) {
      const key = row.key.trim();
      if (!key) continue;
      const vals = parseValues(row.values);
      if (vals.length > 0) out[key] = vals;
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

  const createMutation = useMutation({
    mutationFn: (req: CreateWalkforwardRequest) =>
      api.post<{ id: string }>("/walkforwards", req),
    onSuccess: (data) => {
      router.push(`/walkforwards/${data.id}`);
    },
  });

  const canSubmit = Boolean(
    strategyName &&
      symbol &&
      barResolution &&
      trainBars > 0 &&
      testBars > 0 &&
      numWindows > 0 &&
      Object.keys(paramGrid).length > 0 &&
      numCombos <= MAX_COMBOS &&
      !createMutation.isPending,
  );

  function submit() {
    if (!canSubmit) return;
    createMutation.mutate({
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
    });
  }

  return (
    <AppShell title="New Walk-Forward">
      <div className="space-y-4 max-w-4xl">
        <div>
          <Link
            href="/walkforwards"
            className="text-sm text-indigo-600 hover:underline"
          >
            ← Walk-Forwards
          </Link>
          <h2 className="text-base font-semibold text-navy-700 mt-2">
            Configure a new walk-forward analysis
          </h2>
          <p className="mt-1 text-xs text-gray-500 max-w-2xl">
            Sweep your parameter grid on a rolling training window, then test
            the best params on the next held-out segment. Repeated <em>N</em>{" "}
            times to estimate honest out-of-sample performance.
          </p>
        </div>

        {/* Card 1: Strategy + symbol */}
        <section className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-navy-700 mb-4">
            Strategy &amp; Symbol
          </h3>
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
                {!strategies && <option>Loading…</option>}
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
                {!symbols && <option>Loading…</option>}
                {symbols?.map((s) => (
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
            <h3 className="text-sm font-semibold text-navy-700">
              Parameter Grid
            </h3>
            <span className="text-xs text-gray-500">
              Cartesian product across each row&apos;s values.
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
          <h3 className="text-sm font-semibold text-navy-700 mb-3">
            Walk-Forward Windowing
          </h3>
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

        {createMutation.isError && (
          <div className="bg-red-50 border border-red-200 text-red-800 p-4 rounded-md text-sm">
            {(createMutation.error as Error).message}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
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
            {createMutation.isPending ? "Submitting…" : "Run Walk-Forward"}
          </button>
        </div>

        <div className="text-xs text-gray-500 leading-relaxed pt-2">
          <strong className="text-gray-700">Educational use only.</strong>{" "}
          Walk-forward results are diagnostic, not predictive. Past performance
          on historical windows does not predict future returns. Trading
          involves substantial risk; you may lose your entire investment.
        </div>
      </div>
    </AppShell>
  );
}
