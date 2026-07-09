import { useId } from "react"
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { usePriceHistory } from "../hooks/usePriceHistory.js"
import { COLORS, METAL_ACCENT, tooltipStyle, tooltipLabelStyle, tooltipItemStyle } from "../theme.js"

export default function PriceChart({ metal, range, onPointClick }) {
  const { data, loading, error } = usePriceHistory(metal, range)
  const gradientId = useId()
  const accent = METAL_ACCENT[metal] || COLORS.gold1

  if (loading) return <p className="pf-loading">Loading {metal} prices…</p>
  if (error) return <p className="pf-error">Couldn't load {metal} prices: {error.message}</p>

  function handleClick(chartState) {
    // recharts v3's onClick passes a redux-derived state object (activeIndex,
    // activeLabel, ...), not the v2-style { activePayload } event shape.
    if (!onPointClick || chartState?.activeIndex == null) return
    const point = data[Number(chartState.activeIndex)]
    if (!point) return
    onPointClick({ date: point.date, price: point.price_usd })
  }

  return (
    <div>
      {onPointClick && <p className="pf-chart-hint">Click a point on the chart to log a purchase on that date.</p>}
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart
          data={data}
          margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
          onClick={handleClick}
          style={{ cursor: onPointClick ? "pointer" : "default" }}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={accent} stopOpacity={0.3} />
              <stop offset="100%" stopColor={accent} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={COLORS.rule} />
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: COLORS.inkFaint }} stroke={COLORS.rule} minTickGap={40} />
          <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11, fill: COLORS.inkFaint }} stroke={COLORS.rule} width={60} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelStyle={tooltipLabelStyle}
            itemStyle={tooltipItemStyle}
            formatter={(value) => [`$${value.toFixed(2)}`, "Price"]}
          />
          <Area
            type="monotone"
            dataKey="price_usd"
            stroke={accent}
            strokeWidth={2}
            fill={`url(#${gradientId})`}
            dot={false}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
