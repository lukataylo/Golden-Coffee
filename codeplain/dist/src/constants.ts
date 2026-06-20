import { AutopilotAction, Reading } from './types';

export const SAMPLE_ACTIVITY: AutopilotAction[] = [
  { time: "14:36", title: "Lowered music to 40%", reason: "room is buzzing" },
  { time: "14:21", title: "Warmed the lights", reason: "afternoon lull, keeping people cosy" },
  { time: "13:58", title: "Nudged staff to open a 2nd till", reason: "queue hit 5" },
  { time: "13:30", title: "Started a citrus diffuse", reason: "post-lunch reset" }
];

export const SAMPLE_READING: Reading = {
  comfort: 62,
  occupancy: 18,
  queue: 3,
  sound: 58,
  crowd: 64,
  flow: 71
};

export const STORAGE_KEYS = {
  BACKEND_URL: 'gc_backend',
  BLOB_ID: 'gc_blob'
};

export const DEFAULT_BACKEND_URL = "https://golden-coffee-production.up.railway.app";
export const DEFAULT_BLOB_ID = "demo-snapshot";