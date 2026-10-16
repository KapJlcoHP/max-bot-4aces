import { deadlineCountdown } from "../format";
import type { Step } from "../types";

export default function StepCountdown({ step, tz, now }: {
  step: Pick<Step, "status" | "deadline" | "deadline_time">;
  tz: string;
  now: Date;
}) {
  if (step.status === "done") return null;
  const countdown = deadlineCountdown(step.deadline, step.deadline_time, tz, now);
  return (
    <span className={`step-countdown${countdown.overdue ? " is-overdue" : ""}${!step.deadline ? " no-deadline" : ""}`}>
      {countdown.text}
    </span>
  );
}
