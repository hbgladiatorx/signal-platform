"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AppShell } from "@/components/nav/AppShell";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/useApi";


// ============================================================
// Types
// ============================================================

interface ValidationError {
  code: string;
  message: string;
  line?: number | null;
  col?: number | null;
}

interface TranslateResponse {
  ok: boolean;
  source_code?: string | null;
  class_name?: string | null;
  params_class_name?: string | null;
  suggested_strategy_name?: string | null;
  params_schema?: Record<string, unknown> | null;
  explanation?: string | null;
  validation_errors: ValidationError[];
  llm_error?: string | null;
  input_tokens?: number;
  output_tokens?: number;
}

interface CreateUserStrategyResponse {
  id: string;
  name: string;
  class_name: string;
}


// ============================================================
// Page
// ============================================================
export default function NewStrategyPage() {
  const api = useApi();
  const router = useRouter();
  const queryClient = useQueryClient();

  // ---- Form state ----
  const [nl, setNl] = useState("");
  const [source, setSource] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [explanation, setExplanation] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([]);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [tokenUsage, setTokenUsage] = useState<{ in: number; out: number } | null>(null);

  // ---- Translate mutation ----
  const translateMutation = useMutation<TranslateResponse, Error, string>({
    mutationFn: (description) =>
      api.post<TranslateResponse>("/user-strategies/translate", {
        nl_description: description,
      }),
    onSuccess: (data) => {
      setSource(data.source_code || "");
      setExplanation(data.explanation || null);
      setValidationErrors(data.validation_errors || []);
      setLlmError(data.llm_error || null);
      setTokenUsage(
        data.input_tokens !== undefined
          ? { in: data.input_tokens || 0, out: data.output_tokens || 0 }
          : null,
      );
      // Pre-fill name from suggestion (snake_case → PascalCase)
      if (data.suggested_strategy_name && !name) {
        const pascal = data.suggested_strategy_name
          .split(/[-_]+/)
          .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
          .join("");
        setName(pascal);
      }
    },
    onError: (err) => {
      setLlmError(err.message);
      setSource("");
      setValidationErrors([]);
    },
  });

  // ---- Save mutation ----
  const saveMutation = useMutation<CreateUserStrategyResponse, Error, void>({
    mutationFn: () =>
      api.post<CreateUserStrategyResponse>("/user-strategies", {
        name,
        description: description || null,
        nl_description: nl,
        source_code: source,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
      queryClient.invalidateQueries({ queryKey: ["user-strategies"] });
      router.push("/strategies");
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setServerError(`${err.status}: ${err.detail}`);
      } else {
        setServerError(err.message);
      }
    },
  });

  // ---- Handlers ----
  function handleTranslate() {
    if (!nl.trim()) return;
    setServerError(null);
    setValidationErrors([]);
    setLlmError(null);
    setSource("");
    setExplanation(null);
    translateMutation.mutate(nl);
  }

  function handleSave() {
    if (!source.trim() || !name.trim()) return;
    setServerError(null);
    saveMutation.mutate();
  }

  // ---- Derived state ----
  const hasCode = source.trim().length > 0;
  const canSave =
    hasCode &&
    name.trim().length > 0 &&
    validationErrors.length === 0 &&
    !saveMutation.isPending;

  // ============================================================
  // Render
  // ============================================================
  return (
    <AppShell title="New strategy">
      <div className="max-w-4xl space-y-6">
        {/* Back link */}
        <div>
          <Link
            href="/strategies"
            className="text-xs text-navy-600 hover:underline"
          >
            ← Back to strategies
          </Link>
        </div>

        {/* ============= 1. NL DESCRIPTION ============= */}
        <Card>
          <CardHeader
            title="Describe your strategy"
            subtitle="In plain English. Claude will generate Python source code that you can review and edit before saving."
          />
          <div className="space-y-4 px-6 py-5">
            <textarea
              value={nl}
              onChange={(e) => setNl(e.target.value)}
              placeholder="e.g. Buy BTC when the 14-period RSI drops below 30, sell when it rises above 70. Use a small position size."
              rows={4}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
            />
            <p className="text-xs text-gray-500">
              Tip: be specific about the indicator, threshold, entry &amp; exit
              conditions. Generation takes ~10-15 seconds and costs about $0.02.
            </p>
            {llmError && (
              <ErrorBanner title="LLM error" message={llmError} />
            )}
            <div className="flex items-center justify-between">
              <div className="text-xs text-gray-500">
                {tokenUsage && (
                  <>
                    Tokens: {tokenUsage.in.toLocaleString()} in /{" "}
                    {tokenUsage.out.toLocaleString()} out
                  </>
                )}
              </div>
              <button
                type="button"
                onClick={handleTranslate}
                disabled={translateMutation.isPending || !nl.trim()}
                className="rounded-md bg-navy-600 px-4 py-2 text-sm font-medium text-white hover:bg-navy-700 disabled:cursor-not-allowed disabled:bg-navy-300"
              >
                {translateMutation.isPending
                  ? "Generating (~12s)…"
                  : hasCode
                    ? "Regenerate"
                    : "Generate Python"}
              </button>
            </div>
          </div>
        </Card>

        {/* ============= 2. CODE REVIEW ============= */}
        {hasCode && (
          <Card>
            <CardHeader
              title="Review the generated code"
              subtitle="You can edit before saving. The server re-validates on save."
            />
            <div className="space-y-4 px-6 py-5">
              {explanation && (
                <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">
                  <p className="font-medium text-xs uppercase tracking-wide text-blue-700">
                    Explanation
                  </p>
                  <p className="mt-1">{explanation}</p>
                </div>
              )}

              <textarea
                value={source}
                onChange={(e) => {
                  setSource(e.target.value);
                  // Clear stale validation errors when user edits
                  if (validationErrors.length > 0) {
                    setValidationErrors([]);
                  }
                }}
                rows={20}
                spellCheck={false}
                className="block w-full rounded-md border border-gray-300 bg-gray-50 px-3 py-2 font-mono text-xs leading-relaxed text-gray-900 shadow-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
              />

              {validationErrors.length > 0 && (
                <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3">
                  <p className="text-sm font-medium text-red-800">
                    Validation errors — fix and save, or regenerate:
                  </p>
                  <ul className="mt-2 space-y-1">
                    {validationErrors.map((err, i) => (
                      <li
                        key={i}
                        className="text-sm text-red-700"
                      >
                        <code className="rounded bg-red-100 px-1 text-xs">
                          {err.code}
                        </code>{" "}
                        {err.message}
                        {err.line != null && (
                          <span className="text-red-500">
                            {" "}(line {err.line})
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </Card>
        )}

        {/* ============= 3. SAVE FORM ============= */}
        {hasCode && (
          <Card>
            <CardHeader
              title="Save"
              subtitle="Pick a name. It'll appear in the strategies list and be usable in backtests."
            />
            <div className="space-y-4 px-6 py-5">
              <Field label="Name" required>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="MyStrategy"
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Must be unique among your strategies and not collide with a
                  built-in.
                </p>
              </Field>

              <Field label="Description (optional)">
                <input
                  type="text"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="A brief one-line summary"
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
                />
              </Field>

              {serverError && (
                <ErrorBanner title="Server error" message={serverError} />
              )}

              <div className="flex justify-end gap-3 pt-2">
                <Link
                  href="/strategies"
                  className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </Link>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={!canSave}
                  className="rounded-md bg-navy-600 px-4 py-2 text-sm font-medium text-white hover:bg-navy-700 disabled:cursor-not-allowed disabled:bg-navy-300"
                  title={
                    !canSave && validationErrors.length > 0
                      ? "Fix validation errors first"
                      : !name.trim()
                        ? "Enter a name"
                        : undefined
                  }
                >
                  {saveMutation.isPending ? "Saving…" : "Save strategy"}
                </button>
              </div>
            </div>
          </Card>
        )}
      </div>
    </AppShell>
  );
}


// ============================================================
// Small helpers
// ============================================================

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
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-gray-700">
        {label}
        {required && <span className="ml-1 text-red-500">*</span>}
      </label>
      {children}
    </div>
  );
}

function ErrorBanner({ title, message }: { title: string; message: string }) {
  return (
    <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm">
      <p className="font-medium text-red-800">{title}</p>
      <p className="mt-1 text-red-700">{message}</p>
    </div>
  );
}
