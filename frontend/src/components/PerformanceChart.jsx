import { useEffect, useState } from "react"
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { usePriceHistory } from "../hooks/usePriceHistory.js"
import { computeHoldingsSeries } from "../lib/portfolio.js"
import { COLORS, METAL_ACCENT, tooltipStyle, tooltipLabelStyle, tooltipItemStyle } from "../theme.js"

export default function PerformanceChart({ metal, transactions }) {
  const metalTxns = transactions.filter((t) => t.metal === metal)
  const earliestDate = metalTxns.reduce(
    (min, t) => (min === null || t.date < min ? t.date : min),
    null,
  )

  // Need the full range from the earliest transaction to today, not just a
  // trailing window — an old purchase needs its whole history to chart correctly.
  const primaryRange = earliestDate ? { start: earliestDate } : { days: 365 }

  // A transaction dated today (or the price feed lagging a day or two behind)
  // means `start: earliestDate` can come back with zero rows — nothing on or
  // after that date has synced yet. Fall back to a trailing window so we still
  // have the latest known price to mark that holding against, rather than
  // showing nothing.
  const [useFallback, setUseFallback] = useState(false)
  useEffect(() => {
    setUseFallback(false)
  }, [metal, earliestDate])

  const range = useFallback ? { days: 365 } : primaryRange
  const { data: priceSeries, loading, error } = usePriceHistory(metal, range)

  useEffect(() => {
    if (!loading && !error && priceSeries.length === 0 && !useFallback && earliestDate) {
      setUseFallback(true)
    }
  }, [loading, error, priceSeries, useFallback, earliestDate])

  if (metalTxns.length === 0) {
    return <p className="pf-empty">Add a {metal} transaction to see your simulated performance here.</p>
  }
  if (loading) return <p className="pf-loading">Loading performance…</p>
  if (error) return <p className="pf-error">Couldn't load performance: {error.message}</p>

  const holdings = computeHoldingsSeries(metalTxns, priceSeries)
  if (holdings.length === 0) {
    return (
      <p className="pf-empty">
        No {metal} price data available yet for that date range — try a date on or before the latest update.
      </p>
    )
  }

  const chartData = priceSeries.map((point, i) => ({
    date: point.date,
    price: point.price_usd,
    costBasis: holdings[i].costBasis,
    marketValue: holdings[i].marketValue,
  }))
  // The mark-to-latest-price entry (see computeHoldingsSeries) can have one
  // more point than priceSeries when a transaction lands after the last
  // synced price — append it so the chart/summary reflect that holding too.
  if (holdings.length > priceSeries.length) {
    const extra = holdings[holdings.length - 1]
    chartData.push({ date: extra.date, price: chartData[chartData.length - 1]?.price ?? null, ...extra })
  }

  const latest = holdings[holdings.length - 1]
  const gain = latest.marketValue - latest.costBasis
  const gainPct = latest.costBasis > 0 ? (gain / latest.costBasis) * 100 : 0
  const gainClass = gain >= 0 ? "pf-up" : "pf-down"
  const accent = METAL_ACCENT[metal] || COLORS.gold1

  return (
    <div>
      <p className="pf-summary">
        Current simulated {metal} holdings: {latest.quantity} oz —{" "}
        <span className={gainClass}>
          {gain >= 0 ? "+" : ""}{gain.toFixed(2)} USD ({gainPct.toFixed(1)}%)
        </span>{" "}
        vs cost basis
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={COLORS.rule} />
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: COLORS.inkFaint }} stroke={COLORS.rule} minTickGap={40} />
          <YAxis yAxisId="left" tick={{ fontSize: 11, fill: COLORS.inkFaint }} stroke={COLORS.rule} width={70} />
          <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: COLORS.inkFaint }} stroke={COLORS.rule} width={70} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelStyle={tooltipLabelStyle}
            itemStyle={tooltipItemStyle}
            formatter={(value, name) => [value == null ? "—" : `$${Number(value).toFixed(2)}`, name]}
          />
          <Legend wrapperStyle={{ fontFamily: "inherit", fontSize: 12.5 }} />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="costBasis"
            name="Cost basis (total)"
            stroke={COLORS.gold2}
            dot={false}
            strokeWidth={2}
            isAnimationActive={false}
          />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="marketValue"
            name="Market value (total)"
            stroke={accent}
            dot={false}
            strokeWidth={2}
            isAnimationActive={false}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="price"
            name="Market price (per oz)"
            stroke={COLORS.inkSoft}
            dot={false}
            strokeWidth={1.5}
            strokeDasharray="4 3"
            isAnimationActive={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
