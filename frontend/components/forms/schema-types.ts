/**
 * JSON-schema-ish form definitions.
 *
 * We intentionally don't use full JSON Schema spec — this is a curated
 * subset tuned for trading platform use cases (strategies, settings).
 * Step 13/14 use this to render Settings forms from a server-provided
 * schema; Phase 2+ uses it for strategy parameter UIs.
 */

export type FieldKind =
  | "string"
  | "number"
  | "integer"
  | "boolean"
  | "select"
  | "multiselect"
  | "secret";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SchemaField {
  key: string;
  label: string;
  kind: FieldKind;
  description?: string;
  required?: boolean;
  default?: unknown;
  placeholder?: string;
  /** For number/integer kinds */
  min?: number;
  max?: number;
  step?: number;
  /** For select/multiselect kinds */
  options?: SelectOption[];
  /** When true, the field is shown but disabled */
  readonly?: boolean;
}

export interface FormSchema {
  title?: string;
  description?: string;
  fields: SchemaField[];
}

export type FormValues = Record<string, unknown>;
