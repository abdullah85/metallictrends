export const METALS = ["gold", "silver", "platinum", "palladium"]

async function getJson(url) {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`Request to ${url} failed: ${res.status}`)
  }
  return res.json()
}

export function fetchPriceHistory(metal, { start, end, days } = {}) {
  const params = new URLSearchParams()
  if (start) params.set("start", start)
  if (end) params.set("end", end)
  if (days) params.set("days", days)
  return getJson(`/api/prices/${metal}?${params}`)
}

export function fetchPriceOnDate(metal, date) {
  return getJson(`/api/prices/${metal}/on/${date}`)
}
