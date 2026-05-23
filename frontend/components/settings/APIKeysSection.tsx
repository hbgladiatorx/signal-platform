"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "@/lib/useApi";
import { cn } from "@/lib/utils";
import {
  SERVICE_SCHEMAS,
  type APICredentialCreate,
  type APICredentialSummary,
  type ServiceSchema,
} from "@/lib/types";

export function APIKeysSection() {
  const api = useApi();
  const qc = useQueryClient();

  const listQuery = useQuery({
    queryKey: ["settings", "api-keys"],
    queryFn: () => api.get<APICredentialSummary[]>("/settings/api-keys"),
  });

  const [adding, setAdding] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (body: APICredentialCreate) =>
      api.post<APICredentialSummary>("/settings/api-keys", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings", "api-keys"] });
      setAdding(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete<void>(`/settings/api-keys/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings", "api-keys"] });
      setDeleteConfirmId(null);
    },
  });

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-navy-700">
              External service credentials
            </h2>
            <p className="mt-1 text-xs text-gray-500">
              Encrypted at rest with AES-128 + HMAC-SHA256. After saving,
              the secret cannot be revealed — only deleted and recreated.
            </p>
          </div>
          {!adding && (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="rounded-md bg-navy-600 px-4 py-2 text-sm font-medium text-white hover:bg-navy-700"
            >
              + Add credential
            </button>
          )}
        </div>

        {adding && (
          <div className="border-b border-gray-200 bg-gray-50 px-6 py-5">
            <AddCredentialForm
              onCancel={() => {
                setAdding(false);
                createMutation.reset();
              }}
              onSubmit={(body) => createMutation.mutate(body)}
              isSubmitting={createMutation.isPending}
              errorMessage={
                createMutation.isError
                  ? (createMutation.error as Error).message
                  : null
              }
            />
          </div>
        )}

        {listQuery.isLoading && (
          <div className="px-6 py-8 text-center text-sm text-gray-500">
            Loading…
          </div>
        )}

        {listQuery.error && (
          <div className="px-6 py-8 text-center text-sm text-red-600">
            {(listQuery.error as Error).message}
          </div>
        )}

        {listQuery.data && listQuery.data.length === 0 && !adding && (
          <div className="px-6 py-12 text-center text-sm text-gray-500">
            No credentials configured.
          </div>
        )}

        {listQuery.data && listQuery.data.length > 0 && (
          <table className="w-full text-sm">
            <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-6 py-2 font-medium">Service</th>
                <th className="px-6 py-2 font-medium">Label</th>
                <th className="px-6 py-2 font-medium">Identifier</th>
                <th className="px-6 py-2 font-medium">Added</th>
                <th className="px-6 py-2 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {listQuery.data.map((c) => (
                <tr key={c.id}>
                  <td className="px-6 py-3">
                    <span className="inline-flex rounded-full bg-navy-50 px-2.5 py-0.5 text-xs font-medium text-navy-700">
                      {serviceDisplay(c.service)}
                    </span>
                  </td>
                  <td className="px-6 py-3 text-gray-700">{c.label}</td>
                  <td className="px-6 py-3 font-mono text-xs text-gray-500">
                    {c.last_four ? `…${c.last_four}` : "—"}
                  </td>
                  <td className="px-6 py-3 text-xs text-gray-500">
                    {new Date(c.created_at).toISOString().slice(0, 10)}
                  </td>
                  <td className="px-6 py-3 text-right">
                    {deleteConfirmId === c.id ? (
                      <span className="inline-flex items-center gap-2">
                        <span className="text-xs text-gray-500">
                          Sure?
                        </span>
                        <button
                          type="button"
                          onClick={() => deleteMutation.mutate(c.id)}
                          disabled={deleteMutation.isPending}
                          className="text-xs text-red-600 hover:text-red-700"
                        >
                          Delete
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeleteConfirmId(null)}
                          className="text-xs text-gray-500 hover:text-gray-700"
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setDeleteConfirmId(c.id)}
                        className="text-xs text-gray-500 hover:text-red-600"
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {deleteMutation.isError && (
        <div className="text-sm text-red-600">
          {(deleteMutation.error as Error).message}
        </div>
      )}
    </div>
  );
}

function serviceDisplay(id: string): string {
  return SERVICE_SCHEMAS.find((s) => s.id === id)?.displayName ?? id;
}

function AddCredentialForm({
  onCancel,
  onSubmit,
  isSubmitting,
  errorMessage,
}: {
  onCancel: () => void;
  onSubmit: (body: APICredentialCreate) => void;
  isSubmitting: boolean;
  errorMessage: string | null;
}) {
  const [service, setService] = useState<ServiceSchema>(SERVICE_SCHEMAS[0]);
  const [label, setLabel] = useState("");
  const [payload, setPayload] = useState<Record<string, string>>({});

  const allFilled =
    label.trim().length > 0 &&
    service.fields.every(
      (f) => (payload[f.key] ?? "").trim().length > 0,
    );

  function handleSubmit() {
    if (!allFilled || isSubmitting) return;
    onSubmit({
      service: service.id,
      label: label.trim(),
      payload: Object.fromEntries(
        service.fields.map((f) => [f.key, (payload[f.key] ?? "").trim()]),
      ),
    });
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Service
          </label>
          <select
            value={service.id}
            onChange={(e) => {
              const next = SERVICE_SCHEMAS.find((s) => s.id === e.target.value);
              if (next) {
                setService(next);
                setPayload({});
              }
            }}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
          >
            {SERVICE_SCHEMAS.map((s) => (
              <option key={s.id} value={s.id}>
                {s.displayName}
              </option>
            ))}
          </select>
          {service.helpUrl && (
            <a
              href={service.helpUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-block text-xs text-navy-600 hover:underline"
            >
              Where do I get these? →
            </a>
          )}
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Label
          </label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder='e.g. "Main trading account"'
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {service.fields.map((f) => (
          <div key={f.key}>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              {f.label}
            </label>
            <input
              type="password"
              value={payload[f.key] ?? ""}
              onChange={(e) =>
                setPayload({ ...payload, [f.key]: e.target.value })
              }
              placeholder={f.placeholder}
              autoComplete="off"
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500"
            />
          </div>
        ))}
      </div>

      {errorMessage && (
        <div className="text-sm text-red-600">{errorMessage}</div>
      )}

      <div className="flex items-center justify-end gap-3 border-t border-gray-200 pt-4">
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-gray-600 hover:text-gray-900"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!allFilled || isSubmitting}
          className={cn(
            "rounded-md px-4 py-2 text-sm font-medium text-white transition-colors",
            !allFilled || isSubmitting
              ? "cursor-not-allowed bg-navy-300"
              : "bg-navy-600 hover:bg-navy-700",
          )}
        >
          {isSubmitting ? "Saving…" : "Save credential"}
        </button>
      </div>
    </div>
  );
}
