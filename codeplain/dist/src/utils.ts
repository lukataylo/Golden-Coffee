import { ComfortScore, ComfortBand, Reading } from './types';

/**
 * Derives the Comfort-band from a Comfort-score.
 * 0-39: Quiet, 40-74: Balanced, 75-100: Buzzing
 */
export const getComfortBand = (score: ComfortScore): ComfortBand => {
  if (score < 0 || score > 100) {
    throw new Error(`Invalid Comfort-score: ${score}. Score must be between 0 and 100.`);
  }
  if (score <= 39) return "Quiet";
  if (score <= 74) return "Balanced";
  return "Buzzing";
};

/**
 * Fetches the current reading from the backend.
 * Returns the reading object if successful, otherwise null.
 */
export const fetchReading = async (baseUrl: string): Promise<Reading | null> => {
  try {
    const response = await fetch(`${baseUrl}/comfort`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' }
    });

    if (!response.ok) {
      console.error(`Fetch failed with status: ${response.status} ${response.statusText}`);
      return null;
    }

    const data = await response.json();

    // Defensive check: ensure all required fields are present and valid types
    if (
      typeof data.comfort === 'number' &&
      typeof data.occupancy === 'number' &&
      typeof data.queue === 'number'
    ) {
      return data as Reading;
    } else {
      console.error('Malformed response body received from backend:', data);
      return null;
    }
  } catch (error) {
    console.error(`Network error while fetching reading from ${baseUrl}:`, error);
    return null;
  }
};