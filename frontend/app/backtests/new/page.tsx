"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, Suspense, type FormEvent } from "react";

import { AppShell } from "@/components/nav/AppShell";
import { ApiError } from "@/lib/api";
import type {
  BarResolution,
  CreateBacktestRequest,
  CreateBacktestResponse,
  Strategy,
  StrategyParamSchema,
} from "@/lib/backtest-types";
import { BAR_RESOLUTIONS } from "@/lib/backtest-types";
import type { Instrument } from "@/lib/types";
import { useApi } from "@/lib/useApi";

export default function NewBacktestPage() {
  // Next.js 14 requires useSearchParams to be wrapped in Suspense
  // because static prerendering can't know the search params ahead
  // of time. The inner component does the actual work.
  return (
    <Suspense
      fallback={
        <AppShell title="New backtest">
          <div className="rounded-lg border border-gray-200 bg-white px-6 py-12 text-center text-sm text-gray-500">
            Loading…
          </div>
        </AppShell>
      }
    >
      <NewBacktestForm />
    </Suspense>
  );
}

function NewBacktestForm() {
  const api = useApi();
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const prefilledStrategy = searchParams.get("strategy") ?? "";

  const { data: strategies, isLoading: loadingStrategies } = useQuery({
    queryKey: ["strategies"],
    queryFn: () => api.get<Strategy[]>("/strategies"),
  });

  const { data: instruments, isLoading: loadingInstruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/instruments"),
  });

  // ---------- Form state ----------
  const [strategyName, setStrategyName] = useState<string>(prefilledStrategy);
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([]);
  const [resolution, setResolution] = useState<BarResolution>("1h");
  const [startingCash, setStartingCash] = useState<string>("10000");
  const [feeBps, setFeeBps] = useState<string>("10");
  const [slipBps, setSlipBps] = useState<string>("5");
  const [serverError, setServerError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const selectedStrategy = useMemo(
    () => strategies?.find((s) => s.name === strategyName),
    [strategies, strategyName],
  );

  // Reset params when strategy changes — populate defaults from schema
  useEffect(() => {
    if (selectedStrategy) {
      const next: Record<string, string> = {};
      for (const [key, schema] of Object.entries(
        selectedStrategy.params_schema.properties ?? {},
      )) {
        next[key] = schema.default != null ? String(schema.default) : "";
      }
      setParamValues(next);
    }
  }, [selectedStrategy]);

  // If only one strategy is available, auto-select it.
  useEffect(() => {
    if (
      !strategyName &&
      strategies &&
      strategies.length > 0 &&
      !prefilledStrategy
    ) {
      setStrategyName(strategies[0].name);
    }
  }, [strategies, strategyName, prefilledStrategy]);

  const submit = useMutation<
    CreateBacktestResponse,
    Error,
    CreateBacktestRequest
  >({
    mutationFn: (body) =>
      api.post<CreateBacktestResponse>("/backtests", body),
    onSuccess: () => {
      // Invalidate the list so the new row appears
      queryClient.invalidateQueries({ queryKey: ["backtests"] });
      router.push("/backtests");
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setServerError(`${err.status}: ${err.detail}`);
      } else {
        setServerError(err.message);
      }
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setServerError(null);
    setFieldErrors({});

    // ---------- Client-side validation ----------
    const errs: Record<string, string> = {};

    if (!strategyName) errs.strategy = "Pick a strategy.";
    if (selectedSymbols.length === 0)
      errs.symbols = "Select at least one symbol.";

    // Coerce + validate params from string state
    const coercedParams: Record<string, number | boolean | string> = {};
    if (selectedStrategy) {
      for (const [key, schema] of Object.entries(
        selectedStrategy.params_schema.properties ?? {},
      )) {
        const raw = paramValues[key];
        const v = coerceParamValue(raw, schema);
        if (v === undefined) {
          errs[`param:${key}`] = `Invalid value for ${key}`;
        } else {
          coercedParams[key] = v;
        }
      }
    }

    const cash = Number(startingCash);
    if (!Number.isFinite(cash) || cash <= 0)
      errs.starting_cash = "Must be a positive number.";
    const fee = Number(feeBps);
    if (!Number.isInteger(fee) || fee < 0 || fee > 1000)
      errs.fee_bps = "Integer 0–1000.";
    const slip = Number(slipBps);
    if (!Number.isInteger(slip) || slip < 0 || slip > 1000)
      errs.slip_bps = "Integer 0–1000.";

    if (Object.keys(errs).length > 0) {
      setFieldErrors(errs);
      return;
    }

    submit.mutate({
      strategy_name: strategyName,
      params: coercedParams,
      symbols: selectedSymbols,
      bar_resolution: resolution,
      starting_cash: cash,
      fee_rate_bps: fee,
      slippage_bps: slip,
    });
  }

  // ---------- Render ----------
  if (loadingStrategies || loadingInstruments) {
    return (
      <AppShell title="New backtest">
        <div className="rounded-lg border border-gray-200 bg-white px-6 py-12 text-center text-sm text-gray-500">
          Loading…
        </div>
      </AppShell>
    );
  }

  if (!strategies || strategies.length === 0) {
    return (
      <AppShell title="New backtest">
        <div className="rounded-lg border border-gray-200 bg-white px-6 py-12 text-center text-sm text-gray-500">
          No strategies registered. Add one under{" "}
          <code className="rounded bg-gray-100 px-1">strategies/</code> on
          the server.
        </div>
      </AppShell>
    );
  }

  const paramSchema = selectedStrategy?.params_schema.properties ?? {};
  const paramKeys = Object.keys(paramSchema);
  const activeInstruments = (instruments ?? []).filter((i) => i.active);

  return (
    <AppShell title="New backtest">
      <form onSubmit={handleSubmit} className="max-w-3xl space-y-6">
        {/* ---------- Strategy + params ---------- */}
        <Card>
          <CardHeader
            title="Strategy"
            subtitle="Pick a strategy and configure its parameters."
          />
          <div className="space-y-4 px-6 py-5">
            <Field label="Strategy" required error={fieldErrors.strategy}>
              <select
                value={strategyName}
                onChange={(e) => setStrategyName(e.target.value)}
                className={inputClass}
              >
                <option value="">— Select —</option>
                {strategies.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
              {selectedStrategy?.description && (
                <p className="mt-1 text-xs text-gray-500">
                  {selectedStrategy.description}
                </p>
              )}
            </Field>

            {paramKeys.length > 0 && (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {paramKeys.map((key) => {
                  const schema = paramSchema[key];
                  return (
                    <Field
                      key={key}
                      label={schema.title ?? key}
                      hint={paramHint(schema)}
                      error={fieldErrors[`param:${key}`]}
                    >
                      <input
                        type="number"
                        step={
                          schema.type === "integer" ? "1" : "any"
                        }
                        value={paramValues[key] ?? ""}
                        onChange={(e) =>
                          setParamValues((prev) => ({
                            ...prev,
                            [key]: e.target.value,
                          }))
                        }
                        className={inputClass}
                        placeholder={paramPlaceholder(schema)}
                      />
                      {schema.description && (
                        <p className="mt-1 text-xs text-gray-500">
                          {schema.description}
                        </p>
                      )}
                    </Field>
                  );
                })}
              </div>
            )}
          </div>
        </Card>

        {/* ---------- Symbols + resolution ---------- */}
        <Card>
          <CardHeader
            title="Market data"
            subtitle="Which symbols, sampled at which resolution."
          />
          <div className="space-y-4 px-6 py-5">
            <Field
              label="Symbols"
              required
              error={fieldErrors.symbols}
              hint="Cmd / Ctrl-click to multi-select."
            >
              <select
                multiple
                value={selectedSymbols}
                onChange={(e) =>
                  setSelectedSymbols(
                    Array.from(e.target.selectedOptions).map((o) => o.value),
                  )
                }
                className={`${inputClass} h-32`}
              >
                {activeInstruments.map((inst) => (
                  <option key={inst.id} value={inst.canonical_symbol}>
                    {inst.canonical_symbol}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Bar resolution">
              <div className="flex flex-wrap gap-2">
                {BAR_RESOLUTIONS.map((res) => (
                  <button
                    key={res}
                    type="button"
                    onClick={() => setResolution(res)}
                    className={resolutionButtonClass(res === resolution)}
                  >
                    {res}
                  </button>
                ))}
              </div>
            </Field>
          </div>
        </Card>

        {/* ---------- Execution config ---------- */}
        <Card>
          <CardHeader
            title="Execution"
            subtitle="Simulator knobs — starting cash, fees, slippage."
          />
          <div className="grid grid-cols-1 gap-4 px-6 py-5 sm:grid-cols-3">
            <Field
              label="Starting cash"
              error={fieldErrors.starting_cash}
              hint="USD"
            >
              <input
                type="number"
                step="any"
                value={startingCash}
                onChange={(e) => setStartingCash(e.target.value)}
                className={inputClass}
              />
            </Field>

            <Field
              label="Fee rate"
              error={fieldErrors.fee_bps}
              hint="basis points per fill (10 = 0.10%)"
            >
              <input
                type="number"
                step="1"
                value={feeBps}
                onChange={(e) => setFeeBps(e.target.value)}
                className={inputClass}
              />
            </Field>

            <Field
              label="Slippage"
              error={fieldErrors.slip_bps}
              hint="basis points on market orders (5 = 0.05%)"
            >
              <input
                type="number"
                step="1"
                value={slipBps}
                onChange={(e) => setSlipBps(e.target.value)}
                className={inputClass}
              />
            </Field>
          </div>
        </Card>

        {/* ---------- Server error ---------- */}
        {serverError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <strong>Server error:</strong> {serverError}
          </div>
        )}

        {/* ---------- Submit / cancel ---------- */}
        <div className="flex justify-end gap-3">
          <Link
            href="/backtests"
            className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={submit.isPending}
            className="rounded-md bg-navy-600 px-4 py-2 text-sm font-medium text-white hover:bg-navy-700 disabled:cursor-not-allowed disabled:bg-navy-300"
          >
            {submit.isPending ? "Submitting…" : "Run backtest"}
          </button>
        </div>
      </form>
    </AppShell>
  );
}

// ============================================================
// Helpers
// ============================================================

const inputClass =
  "block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500";

function resolutionButtonClass(active: boolean): string {
  return active
    ? "rounded-md bg-navy-600 px-3 py-1.5 text-sm font-medium text-white"
    : "rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50";
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      {children}
    </div>
  );
}

function CardHeader({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="border-b border-gray-200 px-6 py-4">
      <h2 className="text-base font-semibold text-navy-700">{title}</h2>
      {subtitle && (
        <p className="mt-1 text-xs text-gray-500">{subtitle}</p>
      )}
    </div>
  );
}

function Field({
  label,
  required,
  hint,
  error,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-gray-700">
        {label}
        {required && <span className="ml-1 text-red-500">*</span>}
      </label>
      {children}
      {hint && !error && (
        <p className="mt-1 text-xs text-gray-500">{hint}</p>
      )}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}

function paramHint(schema: StrategyParamSchema): string | undefined {
  const parts: string[] = [];
  if (schema.minimum !== undefined) parts.push(`min: ${schema.minimum}`);
  if (schema.maximum !== undefined) parts.push(`max: ${schema.maximum}`);
  if (schema.default !== undefined)
    parts.push(`default: ${schema.default}`);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

function paramPlaceholder(schema: StrategyParamSchema): string | undefined {
  return schema.default !== undefined ? String(schema.default) : undefined;
}

function coerceParamValue(
  raw: string | undefined,
  schema: StrategyParamSchema,
): number | boolean | string | undefined {
  if (raw === undefined || raw === "") return undefined;
  if (schema.type === "integer") {
    const n = Number(raw);
    if (!Number.isInteger(n)) return undefined;
    return n;
  }
  if (schema.type === "number") {
    const n = Number(raw);
    if (!Number.isFinite(n)) return undefined;
    return n;
  }
  if (schema.type === "boolean") {
    if (raw === "true") return true;
    if (raw === "false") return false;
    return undefined;
  }
  return raw; // string
}
