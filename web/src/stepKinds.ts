import type { Step, StepKind } from "./types";

export const KIND_LABELS: Record<StepKind, string> = {
  unknown: "Вид не уточнён", visit: "Врачебный приём", booking: "Запись на событие",
  investigation: "Исследование / разовая процедура", task: "Задача / документ / административное событие",
  process: "Конкретный этап длительного процесса",
};

export function canBeBookingTarget(kind: StepKind) {
  return ["visit", "investigation", "task", "process"].includes(kind);
}

export function bookingTargets(steps: Step[], booking: Step) {
  return steps.filter((s) => s.id !== booking.id && s.position > booking.position && s.status !== "done" && canBeBookingTarget(s.kind));
}
