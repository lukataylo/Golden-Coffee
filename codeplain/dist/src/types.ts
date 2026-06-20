export type ComfortScore = number; // 0 to 100

export type ComfortBand = "Quiet" | "Balanced" | "Buzzing";

export interface AutopilotAction {
  time: string;
  title: string;
  reason: string;
}

export interface Reading {
  comfort: ComfortScore;
  occupancy: number;
  queue: number;
  sound: number;
  crowd: number;
  flow: number;
}

// New types for AdditionalFunctionality
export type ControlCategory = "music" | "lighting" | "scent";
export type ControlAction = "quieter" | "louder" | "warmer" | "brighter" | "on" | "off";

export interface OverridePayload {
  control: ControlCategory;
  action: ControlAction;
}