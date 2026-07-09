import { useEffect, useState } from "react"
import { fetchPriceOnDate } from "../api.js"

// Fetches the market price for `metal` on `date` — used to default the
// transaction form's price field. Returns null while loading, on error, or
// when either input is missing.
export function usePriceOnDate(metal, date) {
  const [price, setPrice] = useState(null)

  useEffect(() => {
    if (!metal || !date) {
      setPrice(null)
      return
    }
    let cancelled = false
    fetchPriceOnDate(metal, date)
      .then((row) => {
        if (!cancelled) setPrice(row.price_usd)
      })
      .catch(() => {
        if (!cancelled) setPrice(null)
      })
    return () => {
      cancelled = true
    }
  }, [metal, date])

  return price
}
