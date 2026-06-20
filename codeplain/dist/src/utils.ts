import { ComfortScore, ComfortBand } from './types';

/**
 * Derives Comfort-band from Comfort-score.
 * 0-39: Quiet, 40-74: Balanced, 75-100: Buzzing.
 */
export const getComfortBand = (score: ComfortScore): ComfortBand => {
  if (score < 0 || score > 100) {
    throw new Error(`Invalid Comfort-score: ${score}. Score must be between 0 and 100.`);
  }
  if (score <= 39) return "Quiet";
  if (score <= 74) return "Balanced";
  return "Buzzing";
};