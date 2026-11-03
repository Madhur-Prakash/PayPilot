"use client";

/**
 * Bring inventory in from an Excel/CSV export instead of one item at a time.
 *
 * Three steps, each a thin view onto one backend call:
 *   1. Upload       -> POST /inventory/import/preview with no mapping. The
 *                       backend fuzzy-matches columns to fields itself
 *                       ("auto-fill the fields") and validates every row.
 *   2. Map & review -> the merchant can override any column; each change
 *                       re-calls /preview with the edited mapping so the
 *                       validation and row actions (create/update) are always
 *                       current, never guessed at client-side.
 *   3. Result       -> POST /inventory/import/commit with the same mapping,
 *                       writes only the rows that passed.
 */

import {
  AlertTriangle,
  CheckCircle2,
  FileSpreadsheet,
  Loader2,
  Minus,
  Plus,
  Upload,
  UploadCloud,
  XCircle,
} from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/overlays";
import { Badge, Separator } from "@/components/ui/primitives";
import { useInventoryImportCommit, useInventoryImportPreview } from "@/hooks/use-api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { ImportMapping, ImportPreview } from "@/types/api";

const DTYPE_LABEL: Record<string, string> = { string: "Text", number: "Number", boolean: "Yes/No" };
const ACCEPTED = ".csv,.xlsx,.xlsm";

type Step = "upload" | "map" | "result";

export function BulkImportDialog() {
  const canImport = useAuthStore((s) => s.can("inventory:configure"));

  const [open, setOpen] = React.useState(false);
  const [step, setStep] = React.useState<Step>("upload");
  const [file, setFile] = React.useState<File | null>(null);
  const [mapping, setMapping] = React.useState<ImportMapping | null>(null);
  const [preview, setPreview] = React.useState<ImportPreview | null>(null);
  const [dragOver, setDragOver] = React.useState(false);

  const previewMutation = useInventoryImportPreview();
  const commitMutation = useInventoryImportCommit();

  function reset() {
    setStep("upload");
    setFile(null);
    setMapping(null);
    setPreview(null);
    previewMutation.reset();
    commitMutation.reset();
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) reset();
  }

  function chooseFile(chosen: File | null) {
    if (!chosen) return;
    setFile(chosen);
    previewMutation.mutate(
      { file: chosen },
      {
        onSuccess: (data) => {
          setPreview(data);
          setMapping(data.mapping);
          setStep("map");
        },
      },
    );
  }

  function updateMapping(key: string, header: string | null) {
    if (!file || !mapping) return;
    const next = { ...mapping, [key]: header };
    setMapping(next);
    previewMutation.mutate({ file, mapping: next }, { onSuccess: (data) => setPreview(data) });
  }

  function commit() {
    if (!file || !mapping) return;
    commitMutation.mutate({ file, mapping }, { onSuccess: () => setStep("result") });
  }

  if (!canImport) return null;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <Upload className="h-4 w-4" />
          Import
        </Button>
      </DialogTrigger>

      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Import inventory</DialogTitle>
          <DialogDescription>
            {step === "upload" && "Upload a .xlsx or .csv export - columns are matched to fields automatically."}
            {step === "map" && "Review the auto-matched columns, fix any that are wrong, then import."}
            {step === "result" && "Import complete."}
          </DialogDescription>
        </DialogHeader>

        {step === "upload" && (
          <UploadStep
            dragOver={dragOver}
            setDragOver={setDragOver}
            onChoose={chooseFile}
            loading={previewMutation.isPending}
            error={previewMutation.error?.message}
          />
        )}

        {step === "map" && preview && mapping && (
          <MapStep
            preview={preview}
            mapping={mapping}
            onMappingChange={updateMapping}
            remapping={previewMutation.isPending}
          />
        )}

        {step === "result" && commitMutation.data && (
          <ResultStep result={commitMutation.data} />
        )}

        <DialogFooter>
          {step === "map" && (
            <>
              <Button variant="outline" size="sm" onClick={reset}>
                Start over
              </Button>
              <Button
                size="sm"
                onClick={commit}
                loading={commitMutation.isPending}
                disabled={!preview || preview.valid_rows === 0 || previewMutation.isPending}
                className="gap-1.5"
              >
                <UploadCloud className="h-3.5 w-3.5" />
                Import {preview?.valid_rows ?? 0} row{preview?.valid_rows === 1 ? "" : "s"}
              </Button>
            </>
          )}
          {step === "result" && (
            <>
              <Button variant="outline" size="sm" onClick={reset}>
                Import another file
              </Button>
              <Button size="sm" onClick={() => handleOpenChange(false)}>
                Done
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --------------------------------------------------------------------------- //
// Step 1: Upload
// --------------------------------------------------------------------------- //
function UploadStep({
  dragOver,
  setDragOver,
  onChoose,
  loading,
  error,
}: {
  dragOver: boolean;
  setDragOver: (v: boolean) => void;
  onChoose: (file: File | null) => void;
  loading: boolean;
  error?: string;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);

  return (
    <div className="space-y-3">
      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          onChoose(e.dataTransfer.files?.[0] ?? null);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed p-10 text-center transition-colors",
          dragOver ? "border-primary bg-primary/5" : "border-border hover:border-primary/40 hover:bg-muted/40",
          loading && "pointer-events-none opacity-60",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          className="sr-only"
          onChange={(e) => onChoose(e.target.files?.[0] ?? null)}
        />
        {loading ? (
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        ) : (
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-primary">
            <FileSpreadsheet className="h-6 w-6" />
          </div>
        )}
        <div>
          <p className="text-sm font-medium">
            {loading ? "Reading your file…" : "Drop a spreadsheet here, or click to browse"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">.xlsx, .xlsm or .csv, up to 10 MB</p>
        </div>
      </label>

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <XCircle className="h-4 w-4 shrink-0 translate-y-0.5" />
          <span>{error}</span>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Each row updates an item that already exists (matched by SKU) or creates a new one. Existing
        items only have their policy fields touched - stock counts always stay under Adjust Stock.
      </p>
    </div>
  );
}

/** Re-including a field should land on its obvious column, not on "Not mapped". */
function suggestHeader(
  field: ImportPreview["fields"][number],
  columns: ImportPreview["columns"],
): string | null {
  const normalise = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const target = normalise(field.label);
  const exact = columns.find((col) => normalise(col.header) === target);
  if (exact) return exact.header;
  const partial = columns.find(
    (col) => normalise(col.header).includes(target) || target.includes(normalise(col.header)),
  );
  return partial ? partial.header : columns[0]?.header ?? null;
}

/** A plus that adds one of the currently excluded fields back into the import. */
function AddColumnMenu({
  fields,
  columns,
  onAdd,
}: {
  fields: ImportPreview["fields"];
  columns: ImportPreview["columns"];
  onAdd: (key: string, header: string | null) => void;
}) {
  return (
    <Select value="" onValueChange={(key) => {
      const field = fields.find((f) => f.key === key);
      if (field) onAdd(field.key, suggestHeader(field, columns));
    }}>
      <SelectTrigger className="h-8 w-44 text-xs" aria-label="Add a column to import">
        <span className="flex items-center gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          Add a column
        </span>
      </SelectTrigger>
      <SelectContent>
        {fields.map((field) => (
          <SelectItem key={field.key} value={field.key}>
            {field.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// --------------------------------------------------------------------------- //
// Step 2: Map + review
// --------------------------------------------------------------------------- //
function MapStep({
  preview,
  mapping,
  onMappingChange,
  remapping,
}: {
  preview: ImportPreview;
  mapping: ImportMapping;
  onMappingChange: (key: string, header: string | null) => void;
  remapping: boolean;
}) {
  // "Included" is simply "has a column mapped". Required fields stay included
  // even if unmapped, so the missing mapping is visible rather than hidden in
  // the excluded list where nobody would look for it.
  const included = preview.fields.filter(
    (field) => mapping[field.key] != null || field.required,
  );
  const excluded = preview.fields.filter(
    (field) => mapping[field.key] == null && !field.required,
  );

  return (
    <div className={cn("space-y-5", remapping && "opacity-70")}>
      {/* Summary */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <SummaryTile label="Rows in file" value={preview.total_rows} />
        <SummaryTile label="Will create" value={preview.to_create} tone="success" />
        <SummaryTile label="Will update" value={preview.to_update} tone="info" />
        <SummaryTile label="Need fixing" value={preview.error_rows} tone={preview.error_rows ? "destructive" : undefined} />
      </div>

      <Separator />

      {/* Column mapping.

          Split into included and excluded rather than one long list of
          dropdowns: the question an importer is actually asking is "what is
          going into my catalogue?", and a field mapped to "Not mapped" answers
          that far less clearly than one that is simply not in the list. */}
      <div>
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm font-semibold">
            Columns to import{" "}
            <span className="font-normal text-muted-foreground">
              ({included.length} of {preview.fields.length})
            </span>
          </p>
          {excluded.length > 0 && (
            <AddColumnMenu
              fields={excluded}
              columns={preview.columns}
              onAdd={onMappingChange}
            />
          )}
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          {included.map((field) => (
            <div
              key={field.key}
              className="flex items-center justify-between gap-2 rounded-lg border border-border/60 bg-card px-2.5 py-2"
            >
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 truncate text-xs font-medium">
                  {field.label}
                  {field.required && <span className="text-destructive">*</span>}
                </p>
                <p className="truncate text-2xs text-muted-foreground" title={field.description}>
                  {field.description}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Select
                  value={mapping[field.key] ?? "__none__"}
                  onValueChange={(value) =>
                    onMappingChange(field.key, value === "__none__" ? null : value)
                  }
                >
                  <SelectTrigger className="h-8 w-44 text-xs" title="Column from your file">
                    <SelectValue placeholder="Not mapped" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">Not mapped</SelectItem>
                    {preview.columns.map((col) => (
                      <SelectItem key={col.header} value={col.header}>
                        {col.header}
                        <span className="ml-1.5 text-2xs text-muted-foreground">
                          ({DTYPE_LABEL[col.inferred_type] ?? col.inferred_type})
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {/* SKU and Product name identify the row; without them every
                    row fails validation, so they cannot be dropped. */}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-muted-foreground hover:text-destructive"
                  disabled={field.required}
                  title={
                    field.required
                      ? `${field.label} is required to identify each row`
                      : `Do not import ${field.label}`
                  }
                  aria-label={`Remove ${field.label}`}
                  onClick={() => onMappingChange(field.key, null)}
                >
                  <Minus className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </div>

        {excluded.length > 0 && (
          <div className="mt-3 rounded-lg border border-dashed border-border bg-muted/30 p-2.5">
            <p className="text-2xs font-medium text-muted-foreground">
              Not importing ({excluded.length})
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {excluded.map((field) => (
                <button
                  key={field.key}
                  type="button"
                  onClick={() => onMappingChange(field.key, suggestHeader(field, preview.columns))}
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-2xs transition-colors hover:border-primary/50 hover:text-primary focus-ring"
                  title={`Import ${field.label}`}
                >
                  <Plus className="h-3 w-3" />
                  {field.label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-2xs text-muted-foreground">
              Excluded fields are left untouched on an existing item, and take their default
              on a new one.
            </p>
          </div>
        )}
      </div>

      <Separator />

      {/* Row preview */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm font-semibold">
            Preview{" "}
            <span className="font-normal text-muted-foreground">
              (first {preview.rows.length} of {preview.total_rows})
            </span>
          </p>
          {remapping && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        <div className="max-h-72 space-y-1.5 overflow-y-auto rounded-xl bg-muted/20 p-2">
          {preview.rows.map((row) => (
            <div
              key={row.row_number}
              className={cn(
                "rounded-lg border bg-card px-3 py-2 text-xs",
                row.errors.length ? "border-destructive/30" : "border-border/60",
              )}
            >
              <div className="flex items-center gap-2">
                <span className="w-8 shrink-0 text-2xs text-muted-foreground">#{row.row_number}</span>
                {row.errors.length ? (
                  <Badge variant="destructive" className="gap-1 shrink-0">
                    <AlertTriangle className="h-3 w-3" />
                    Error
                  </Badge>
                ) : (
                  <Badge variant={row.action === "create" ? "success" : "info"} className="shrink-0">
                    {row.action === "create" ? "New" : "Update"}
                  </Badge>
                )}
                <span className="truncate font-medium">
                  {row.sku || <span className="italic text-muted-foreground">no SKU</span>}
                </span>
                {typeof row.values.product_name === "string" && (
                  <span className="truncate text-muted-foreground">— {row.values.product_name}</span>
                )}
              </div>
              {row.errors.length > 0 && (
                <ul className="mt-1 space-y-0.5 pl-10 text-2xs text-destructive">
                  {row.errors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SummaryTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "success" | "destructive" | "info";
}) {
  return (
    <div className="rounded-xl border border-border/60 bg-card px-3 py-2.5 text-center">
      <p
        className={cn(
          "text-lg font-bold tabular-nums",
          tone === "success" && "text-success",
          tone === "destructive" && "text-destructive",
          tone === "info" && "text-primary",
        )}
      >
        {value}
      </p>
      <p className="text-2xs text-muted-foreground">{label}</p>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Step 3: Result
// --------------------------------------------------------------------------- //
function ResultStep({
  result,
}: {
  result: {
    total_rows: number;
    created: number;
    updated: number;
    skipped: number;
    failed: number;
    row_errors: { row_number: number; sku: string; message: string }[];
  };
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 rounded-xl border border-border/60 bg-card p-4">
        <div
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
            result.failed > 0 ? "bg-warning/10 text-warning" : "bg-success/10 text-success",
          )}
        >
          <CheckCircle2 className="h-5 w-5" />
        </div>
        <div>
          <p className="text-sm font-semibold">
            {result.created} created, {result.updated} updated
          </p>
          <p className="text-xs text-muted-foreground">
            {result.skipped} skipped, {result.failed} failed - out of {result.total_rows} rows.
          </p>
        </div>
      </div>

      {result.row_errors.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-semibold text-muted-foreground">Row-level failures</p>
          <div className="max-h-48 space-y-1 overflow-y-auto">
            {result.row_errors.map((e) => (
              <p key={e.row_number} className="rounded-lg bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive">
                Row #{e.row_number} ({e.sku}): {e.message}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
