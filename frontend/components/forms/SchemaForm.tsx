"use client";

import { useState, type FormEvent } from "react";

import { cn } from "@/lib/utils";

import type { FormSchema, FormValues, SchemaField } from "./schema-types";

/**
 * Renders a form from a FormSchema and tracks values in local state.
 *
 * The parent receives the current values via onSubmit. Validation is
 * minimal in Phase 1 (required + type coercion). Phase 2+ we can plug
 * in Zod or Ajv for fuller validation.
 */
export function SchemaForm({
  schema,
  initialValues,
  onSubmit,
  submitLabel = "Save",
  isSubmitting = false,
}: {
  schema: FormSchema;
  initialValues?: FormValues;
  onSubmit: (values: FormValues) => void;
  submitLabel?: string;
  isSubmitting?: boolean;
}) {
  const [values, setValues] = useState<FormValues>(() => {
    const seed: FormValues = {};
    for (const field of schema.fields) {
      seed[field.key] =
        initialValues?.[field.key] ?? field.default ?? defaultForKind(field);
    }
    return seed;
  });

  function update(key: string, value: unknown) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSubmit(values);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {schema.title && (
        <div>
          <h2 className="text-lg font-semibold text-navy-700">{schema.title}</h2>
          {schema.description && (
            <p className="mt-1 text-sm text-gray-600">{schema.description}</p>
          )}
        </div>
      )}

      <div className="space-y-4">
        {schema.fields.map((field) => (
          <FieldRow
            key={field.key}
            field={field}
            value={values[field.key]}
            onChange={(v) => update(field.key, v)}
          />
        ))}
      </div>

      <div className="flex justify-end pt-2">
        <button
          type="submit"
          disabled={isSubmitting}
          className={cn(
            "rounded-md bg-navy-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-700",
            "disabled:bg-navy-300 disabled:cursor-not-allowed",
          )}
        >
          {isSubmitting ? "Saving…" : submitLabel}
        </button>
      </div>
    </form>
  );
}

function defaultForKind(field: SchemaField): unknown {
  switch (field.kind) {
    case "boolean":
      return false;
    case "number":
    case "integer":
      return field.min ?? 0;
    case "multiselect":
      return [];
    default:
      return "";
  }
}

function FieldRow({
  field,
  value,
  onChange,
}: {
  field: SchemaField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const inputClass = cn(
    "block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm",
    "focus:border-navy-500 focus:outline-none focus:ring-1 focus:ring-navy-500",
    "disabled:bg-gray-50 disabled:text-gray-500",
  );

  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-gray-700">
        {field.label}
        {field.required && <span className="ml-1 text-red-500">*</span>}
      </label>

      {field.kind === "string" && (
        <input
          type="text"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder}
          required={field.required}
          disabled={field.readonly}
          className={inputClass}
        />
      )}

      {field.kind === "secret" && (
        <input
          type="password"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder ?? "•••••••"}
          required={field.required}
          disabled={field.readonly}
          autoComplete="off"
          className={inputClass}
        />
      )}

      {(field.kind === "number" || field.kind === "integer") && (
        <input
          type="number"
          value={(value as number | string) ?? ""}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") {
              onChange("");
            } else {
              const n =
                field.kind === "integer" ? parseInt(raw, 10) : parseFloat(raw);
              onChange(Number.isNaN(n) ? raw : n);
            }
          }}
          min={field.min}
          max={field.max}
          step={field.step ?? (field.kind === "integer" ? 1 : "any")}
          placeholder={field.placeholder}
          required={field.required}
          disabled={field.readonly}
          className={inputClass}
        />
      )}

      {field.kind === "boolean" && (
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
            disabled={field.readonly}
            className="h-4 w-4 rounded border-gray-300 text-navy-600 focus:ring-navy-500"
          />
          <span className="text-sm text-gray-700">
            {field.description ?? "Enabled"}
          </span>
        </label>
      )}

      {field.kind === "select" && (
        <select
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
          disabled={field.readonly}
          className={inputClass}
        >
          {!field.required && <option value="">— select —</option>}
          {field.options?.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      )}

      {field.kind === "multiselect" && (
        <select
          multiple
          value={(value as string[]) ?? []}
          onChange={(e) =>
            onChange(
              Array.from(e.target.selectedOptions).map((opt) => opt.value),
            )
          }
          disabled={field.readonly}
          className={cn(inputClass, "h-32")}
        >
          {field.options?.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      )}

      {field.description && field.kind !== "boolean" && (
        <p className="mt-1 text-xs text-gray-500">{field.description}</p>
      )}
    </div>
  );
}
