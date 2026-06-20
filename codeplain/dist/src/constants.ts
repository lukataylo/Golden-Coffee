import { Alert, Reading } from './types';

export const SAMPLE_READING: Reading = {
  comfort: 62,
  occupancy: 18,
  queue: 3
};

export const SAMPLE_ALERTS: Alert[] = [
  { time: "14:32", level: "warn", message: "High occupancy detected in Zone B" },
  { time: "14:15", level: "info", message: "HVAC system switched to optimal mode" },
  { time: "13:50", level: "info", message: "Daily cleaning completed" }
];

export const STORAGE_KEYS = {
  BACKEND_URL: 'gc_backend'
};

export const DEFAULT_BACKEND_URL = "https://golden-coffee-production.up.railway.app";