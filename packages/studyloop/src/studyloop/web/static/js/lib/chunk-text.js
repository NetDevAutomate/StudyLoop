/**
 * Shared helpers for agent chunk payloads and energy-adaptive timers.
 */

export function extractChunkText(payload) {
  if (!payload) return '';

  const content = payload.content;
  if (content && typeof content === 'object' && !Array.isArray(content)) {
    return typeof content.text === 'string' ? content.text : '';
  }
  if (Array.isArray(content) && content.length > 0 && typeof content[0] === 'object') {
    return typeof content[0].text === 'string' ? content[0].text : '';
  }
  return typeof payload.text === 'string' ? payload.text : '';
}

export function energyBand(energy) {
  if (energy >= 7) return 'high';
  if (energy >= 4) return 'medium';
  return 'low';
}
