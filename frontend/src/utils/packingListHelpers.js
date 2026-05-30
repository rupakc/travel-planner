/**
 * packingListHelpers.js
 * Utilities for packing list weight calculations and localStorage persistence.
 */

/**
 * Known item weights in grams, keyed by lowercase item name (or substring).
 * Lookup is case-insensitive and checks for substring matches as a fallback.
 */
const ITEM_WEIGHTS = {
  passport: 50,
  adapter: 100,
  'phone charger': 80,
  charger: 80,
  laptop: 1500,
  camera: 500,
  'waterproof jacket': 300,
  jacket: 300,
  'walking shoes': 600,
  shoes: 600,
  'hiking boots': 900,
  boots: 900,
  swimsuit: 150,
  sunscreen: 200,
};

const DEFAULT_WEIGHT_GRAMS = 200;

/**
 * Return the estimated weight in grams for a named packing item.
 * Matching is case-insensitive; an exact key match is tried first, then
 * a substring scan so that e.g. "My phone charger (USB-C)" still hits 80 g.
 *
 * @param {string} itemName
 * @returns {number} weight in grams
 */
export function getItemWeight(itemName) {
  if (!itemName || typeof itemName !== 'string') return DEFAULT_WEIGHT_GRAMS;

  const lower = itemName.toLowerCase();

  // Exact match first
  if (Object.prototype.hasOwnProperty.call(ITEM_WEIGHTS, lower)) {
    return ITEM_WEIGHTS[lower];
  }

  // Longest-key-first substring scan so "waterproof jacket" beats "jacket"
  const keys = Object.keys(ITEM_WEIGHTS).sort((a, b) => b.length - a.length);
  for (const key of keys) {
    if (lower.includes(key)) return ITEM_WEIGHTS[key];
  }

  return DEFAULT_WEIGHT_GRAMS;
}

/**
 * Format a weight in grams to a human-readable string.
 * Values >= 1000 g are shown as "X.X kg"; smaller values as "X g".
 *
 * @param {number} grams
 * @returns {string}
 */
export function formatWeight(grams) {
  if (typeof grams !== 'number' || isNaN(grams)) return '0 g';
  if (grams >= 1000) {
    return `${(grams / 1000).toFixed(1)} kg`;
  }
  return `${Math.round(grams)} g`;
}

/**
 * Load the checked packing-list state for a trip from localStorage.
 *
 * @param {string} tripId
 * @returns {Set<string>} set of checked item identifiers
 */
export function loadPackingState(tripId) {
  const key = `packing_${tripId}`;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return new Set(parsed);
    return new Set();
  } catch {
    return new Set();
  }
}

/**
 * Persist the checked packing-list state for a trip to localStorage.
 *
 * @param {string} tripId
 * @param {Set<string>} checkedSet
 */
export function savePackingState(tripId, checkedSet) {
  const key = `packing_${tripId}`;
  try {
    const arr = Array.from(checkedSet);
    localStorage.setItem(key, JSON.stringify(arr));
  } catch {
    // Silently ignore quota / private-browsing errors
  }
}
