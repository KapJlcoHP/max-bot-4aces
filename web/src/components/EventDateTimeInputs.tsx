/** Event wall-clock fields: never convert through the device timezone. */
export default function EventDateTimeInputs({ date, time, onChange, disabled = false, label = "Срок" }: {
  date: string;
  time: string;
  onChange: (date: string, time: string) => void;
  disabled?: boolean;
  label?: string;
}) {
  return <div className="step-date-time-row">
    <label className="step-date-time-field">{label}
      <input type="date" aria-label={label} value={date} disabled={disabled} style={{ width: "100%" }}
        onChange={(e) => onChange(e.target.value, e.target.value ? time : "")} />
    </label>
    <label className="step-date-time-field">Время (необязательно)
      <input type="time" aria-label={`${label}: время (необязательно)`} value={time} disabled={disabled || !date} style={{ width: "100%" }}
        onChange={(e) => onChange(date, e.target.value)} />
    </label>
  </div>;
}
