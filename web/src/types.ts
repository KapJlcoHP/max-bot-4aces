export interface UserDto {
  id: number;
  max_user_id: number;
  first_name: string;
  last_name: string;
  email: string;
  avatar_url: string;
  notifications_on: boolean;
  notify_day_before: boolean;
  notify_hour_before: boolean;
  notify_at_deadline: boolean;
  step_day_before_time: string;
  tz: string;
  region: string;
  attached_clinic_id: number | null;
  consent_at: string | null;
}

export interface Region {
  key: string;
  title: string;
  pilot: boolean;
}

export interface Situation {
  key: string;
  title: string;
  description: string;
  icon: string;
}

export type StepSource = "template" | "user" | "doctor";

export interface ContentSource {
  id: string;
  title: string;
  url: string;
  checked_at: string | null;
  checked_by: string | null;
  checked_where: string | null;
  scope: string;
}

export interface Step {
  id: number;
  position: number;
  title: string;
  description: string;
  place: string;
  deadline: string | null;
  deadline_time: string | null;
  status: "pending" | "current" | "done";
  has_checklist: boolean;
  note: string | null;
  source: StepSource;
  reason: string;
  source_id: string | null;
  source_info: ContentSource | null;
  completed_at?: string | null;
}

export interface RouteDto {
  id: number;
  situation_key: string;
  title: string;
  subtitle: string;
  active: boolean;
  total_steps: number;
  done_steps: number;
  steps: Step[];
}

export interface CompleteStepResult {
  step: Step;
  route: RouteDto;
  next_step: Step | null;
}

export interface CustomStepIn {
  title: string;
  deadline?: string | null;
  deadline_time?: string | null;
}

/** Omitted fields are preserved; null date also clears the event time. */
export interface StepUpdateIn {
  deadline?: string | null;
  deadline_time?: string | null;
}

export interface ChecklistItem {
  id: number;
  title: string;
  collected: boolean;
}

export interface Checklist {
  items: ChecklistItem[];
  collected: number;
  total: number;
}

export interface Organization {
  id: number;
  title: string;
  org_type: string;
  region: string;
  address: string;
  phone: string;
  hours: string;
  services: string[];
  lat: number | null;
  lon: number | null;
}

/** Публичная конфигурация Yandex Maps JS API, отдаваемая сервером. */
export interface MapConfig {
  api_key: string;
  lang?: string;
  enabled: boolean;
}

export interface ConsentPayload {
  tz: string;
  region: string;
  attached_clinic_id: number | null;
  diaries: HealthSetting[];
}

export interface Reminder {
  id: number;
  title: string;
  place: string;
  at: string;
  enabled: boolean;
}

export type HealthType = "bp" | "weight" | "sugar" | "mood";

export interface HealthRecord {
  id: number;
  type: HealthType;
  at: string;
  systolic: number | null;
  diastolic: number | null;
  pulse: number | null;
  weight_kg: number | null;
  sugar_mmol: number | null;
  meal_tag: string | null;
  mood: string | null;
  pain: number | null;
  tag: string | null;
  note: string | null;
}

export interface HealthSetting {
  diary: HealthType;
  enabled: boolean;
  /** "HH:MM" — время напоминания от бота; null — напоминание выключено */
  push_time: string | null;
}

export interface MedSlot {
  course_id: number;
  name: string;
  at_time: string;
  taken: boolean;
  taken_at: string | null;
}

export interface MedCourse {
  id: number;
  name: string;
  times: string[];
  until: string | null;
  enabled: boolean;
}

export interface MedsOut {
  courses: MedCourse[];
  today: MedSlot[];
}

export interface ReportMedsRow {
  name: string;
  taken: number;
  planned: number;
  pct: number;
}

export interface ReportNote {
  at: string;
  note: string;
}

export interface HealthReport {
  period_days: number;
  bp_count: number;
  bp_avg: string | null;
  pulse_avg: number | null;
  weight_latest: number | null;
  weight_delta: number | null;
  weight_count: number;
  sugar_avg: number | null;
  sugar_count: number;
  meds: ReportMedsRow[];
  notes: ReportNote[];
}

export interface FamilyMember {
  id: number;
  name: string;
  role: string;
  color: string;
}
