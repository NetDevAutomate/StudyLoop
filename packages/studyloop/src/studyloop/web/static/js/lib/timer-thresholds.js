/**
 * Energy-adaptive break thresholds, in minutes.
 *
 * `green` is the point at which a break becomes worth taking; `amber` is the
 * point at which it stops being optional. Lower energy means shorter intervals,
 * which is the whole design: a low-energy day needs more frequent, smaller
 * chunks rather than the same block delivered with more willpower.
 *
 * These mirror the Python side and the CSS colour phases. Changing them in one
 * place only will desynchronise the timer's colour from the sidebar's label, so
 * they are documented here as a shared contract rather than a local constant.
 * See agents/shared/break-science.md for the reasoning behind the numbers.
 *
 * Extracted from index.html's inline script, where it was a module-level const
 * that only `sessionTimer` consumed.
 */
export const THRESHOLDS = {
  high: { green: 25, amber: 50 },
  medium: { green: 20, amber: 40 },
  low: { green: 15, amber: 30 },
};
