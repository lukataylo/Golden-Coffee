export type ComfortScore = number; // 0 to 100

export type ComfortBand = "Quiet" | "Balanced" | "Buzzing";

export interface Alert {
  time: string;
  level: "info" | "warn";
  message: string;
}

export interface Reading {
  comfort: ComfortScore;
  occupancy: number;
  queue: number;
}