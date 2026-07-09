import { useEffect, useState } from "react"
import { fetchPriceHistory } from "../api.js"

// Fetches a metal's price series. `range` is `{ days }` or `{ start, end }` —
// same shape the /api/prices/{metal} endpoint accepts.
export function usePriceHistory(metal, range) {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const { start, end, days } = range

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchPriceHistory(metal, { start, end, days })
      .then((rows) => {
        if (!cancelled) setData(rows)
      })
      .catch((err) => {
        if (!cancelled) setError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [metal, start, end, days])

  return { data, loading, error }
}
