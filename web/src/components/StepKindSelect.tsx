import type { StepKind } from "../types";
import { KIND_LABELS } from "../stepKinds";

export default function StepKindSelect({ value, onChange, disabled, label = "Вид шага" }: {
  value: StepKind; onChange: (kind: StepKind) => void; disabled?: boolean; label?: string;
}) {
  return <label className="kind-select">{label}
    <select aria-label={label} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value as StepKind)}>
      {Object.entries(KIND_LABELS).map(([kind, title]) => <option key={kind} value={kind}>{title}</option>)}
    </select>
  </label>;
}
