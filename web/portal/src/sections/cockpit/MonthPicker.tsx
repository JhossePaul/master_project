import { formatMonth } from "@/lib/format";

export function MonthPicker({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string | null;
  onChange: (m: string | null) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      Mes
      <select
        className="h-9 rounded-sm border border-border-strong bg-surface px-2"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">Último con revisión humana</option>
        {[...options].reverse().map((m) => (
          <option key={m} value={m}>
            {formatMonth(m)}
          </option>
        ))}
      </select>
    </label>
  );
}
