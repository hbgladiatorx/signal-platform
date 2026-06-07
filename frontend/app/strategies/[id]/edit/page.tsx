"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/nav/AppShell";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/useApi";

// ============================================================
// Types (mirror the user-strategies API)
// ============================================================
interface ValidationError {
  code: string;
  message: string;
  line?: number | null;
  col?: number | null;
}

interface ValidateResponse {
  ok: boolean;
  errors: ValidationError[];
  class_name?: string | null;
  params_class_name?: string | null;
  params_schema?: Record<string, unknown> | null;
}

interface UserStrategyDetail {
  id: string;
  name: string;
  description?: string | null;
  nl_description?: string | null;
  class_name: string;
  source_code: string;
  params_schema: Record<string, unknown>;
  is_active: boolean;
}

// ============================================================
// Page
// ============================================================
export default function EditStrategyPage() {
  const api = useApi();
  const router = useRouter();
  const queryClient = useQueryClient();
  const params = useParams();
  const id = (params?.id as string) ?? "";

  const { data, isLoading, error } = useQuery({
    queryKey: ["user-strategy", id],
    queryFn: () => api.get<UserStrategyDetail>(`/user-strategies/${id}`),
    enabled: id.length > 0,
  });

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState("");
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([]);
  const [serverError, setServerError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Populate the form once, when the strategy loads.
  useEffect(() => {
    if (data && !loaded) {
      setName(data.name);
      setDescription(data.description ?? "");
      setSource(data.source_code);
      setLoaded(true);
    }
  }, [data, loaded]);

  const validateMutation = useMutation<ValidateResponse, Error, string>({
    mutationFn: (src) =>
      api.post<ValidateResponse>("/user-strategies/validate", { source_code: src }),
    onSuccess: (res) => setValidationErrors(res.ok ? [] : res.errors),
    onError: (err) => setServerError(err.message),
  });

  const saveMutation = useMutation<UserStrategyDetail, Error, void>({
    mutationFn: () =>
      api.put<UserStrategyDetail>(`/user-strategies/${id}`, {
        name,
        description: description || null,
        source_code: source,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
      queryClient.invalidateQueries({ queryKey: ["user-strategies"] });
      queryClient.invalidateQueries({ queryKey: ["user-strategy", id] });
      router.push("/strategies");
    },
    onError: (err) => {
      setServerError(err instanceof ApiError ? `${err.status}: ${err.detail}` : err.message);
    },
  });

  if (isLoading) {
    return (
      <AppShell title="Edit strategy">
        <div className="rounded-lg border border-gray-200 bg-white px-6 py-12 text-center text-sm text-gray-500">
          Loading…
        </div>
      </AppShell>
    );
  }

  if (error) {
    return (
      <AppShell title="Edit strategy">
        <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
          Failed to load strategy: {(error as Error).message}
        </div>
      </AppShell>
    );
  }

  const canSave =
    name.trim().length > 0 &&
    source.trim().length > 0 &&
    validationErrors.length === 0 &&
    !saveMutation.isPending;

  return (
    <AppShell title="Edit strategy">
      <div className="max-w-4xl space-y-6">
        <div>
          <Link href="/strategies" className="text-xs text-navy-600 hover:underline">
            ← Back to strategies
          </Link>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-6 py-4">
            <h2 className="text-base font-semibold text-navy-700">Details</h2>
          </div>
          <div className="space-y-4 px-6 py-5">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Name<span className="ml-1 text-red-500">*</span>
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Description (optional)
              </label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
              />
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-6 py-4">
            <h2 className="text-base font-semibold text-navy-700">Source code</h2>
            <p className="mt-1 text-xs text-gray-500">
              Edit the Python directly. Use “Validate” to check before saving; the
              server re-validates on save too.
            </p>
          </div>
          <div className="space-y-4 px-6 py-5">
            <textarea
              value={source}
              onChange={(e) => {
                setSource(e.target.value);
                if (validationErrors.length > 0) setValidationErrors([]);
              }}
              rows={20}
              spellCheck={false}
              className="block w-full rounded-md border border-gray-300 bg-gray-50 px-3 py-2 font-mono text-xs leading-relaxed text-gray-900 shadow-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
            />

            {validationErrors.length > 0 && (
              <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3">
                <p className="text-sm font-medium text-red-800">Validation errors:</p>
                <ul className="mt-2 space-y-1">
                  {validationErrors.map((err, i) => (
                    <li key={i} className="text-sm text-red-700">
                      <code className="rounded bg-red-100 px-1 text-xs">{err.code}</code>{" "}
                      {err.message}
                      {err.line != null && (
                        <span className="text-red-500"> (line {err.line})</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {serverError && (
              <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm">
                <p className="font-medium text-red-800">Server error</p>
                <p className="mt-1 text-red-700">{serverError}</p>
              </div>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setServerError(null);
                  validateMutation.mutate(source);
                }}
                disabled={validateMutation.isPending || !source.trim()}
                className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                {validateMutation.isPending ? "Validating…" : "Validate"}
              </button>
              <Link
                href="/strategies"
                className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </Link>
              <button
                type="button"
                onClick={() => {
                  setServerError(null);
                  saveMutation.mutate();
                }}
                disabled={!canSave}
                className="rounded-md bg-navy-600 px-4 py-2 text-sm font-medium text-white hover:bg-navy-700 disabled:cursor-not-allowed disabled:bg-navy-300"
              >
                {saveMutation.isPending ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
