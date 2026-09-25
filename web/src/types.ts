export interface UserDto {
  id: number;
  max_user_id: number;
  first_name: string;
  last_name: string;
  email: string;
  notifications_on: boolean;
}

export interface Situation {
  key: string;
  title: string;
  description: string;
  icon: string;
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
  address: string;
  phone: string;
  hours: string;
  services: string[];
}

export interface Reminder {
  id: number;
  title: string;
  place: string;
  at: string;
  enabled: boolean;
}

export interface BpRecord {
  id: number;
  at: string;
  systolic: number;
  diastolic: number;
  pulse: number;
}

export interface FamilyMember {
  id: number;
  name: string;
  role: string;
  color: string;
}
