import type { Resource } from "../types/library";

function normalize(value: string) {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ");
}

function levenshtein(a: string, b: string) {
  const rows = a.length + 1;
  const cols = b.length + 1;
  const dp = Array.from({ length: rows }, () => Array<number>(cols).fill(0));

  for (let i = 0; i < rows; i += 1) dp[i][0] = i;
  for (let j = 0; j < cols; j += 1) dp[0][j] = j;

  for (let i = 1; i < rows; i += 1) {
    for (let j = 1; j < cols; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(
        dp[i - 1][j] + 1,
        dp[i][j - 1] + 1,
        dp[i - 1][j - 1] + cost,
      );
    }
  }

  return dp[a.length][b.length];
}

function fuzzyWordScore(query: string, candidate: string) {
  if (!query || !candidate) return 0;
  if (candidate === query) return 140;
  if (candidate.startsWith(query)) return 120;
  if (candidate.includes(query)) return 90;

  const distance = levenshtein(query, candidate);
  const threshold = Math.max(1, Math.floor(query.length / 3));
  if (distance <= threshold) {
    return 70 - distance * 10;
  }

  return 0;
}

function fieldScore(query: string, value: string) {
  const normalizedValue = normalize(value);
  if (!normalizedValue) return 0;

  if (normalizedValue === query) return 260;
  if (normalizedValue.startsWith(query)) return 220;
  if (normalizedValue.includes(query)) return 180;

  const words = normalizedValue.split(" ").filter(Boolean);
  const bestWord = words.reduce((best, word) => Math.max(best, fuzzyWordScore(query, word)), 0);
  const phraseScore = fuzzyWordScore(query, normalizedValue);

  return Math.max(bestWord, phraseScore);
}

function resourceScore(resource: Resource, rawQuery: string) {
  const query = normalize(rawQuery);
  if (!query) return 1;

  const titleScore = fieldScore(query, resource.title);
  const authorScore = fieldScore(query, resource.author);
  const categoryScore = fieldScore(query, resource.category);

  const tokenBonus = query
    .split(" ")
    .filter(Boolean)
    .reduce((score, token) => {
      const tokenTitle = fieldScore(token, resource.title);
      const tokenAuthor = fieldScore(token, resource.author);
      const tokenCategory = fieldScore(token, resource.category);
      return score + Math.max(tokenTitle, tokenAuthor, tokenCategory, 0);
    }, 0);

  return titleScore * 3 + authorScore * 2 + categoryScore + tokenBonus;
}

export function rankResources(resources: Resource[], rawQuery: string) {
  const query = normalize(rawQuery);
  if (!query) return resources;

  return resources
    .map((resource) => ({
      resource,
      score: resourceScore(resource, query),
    }))
    .filter((entry) => entry.score > 0)
    .sort((left, right) => right.score - left.score || left.resource.title.localeCompare(right.resource.title))
    .map((entry) => entry.resource);
}
