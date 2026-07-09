// Turns a list of paper buy/sell transactions for one metal, plus that metal's
// daily price series, into a day-by-day view of what the user would be holding:
// how much, what it cost (weighted-average cost basis — simpler than FIFO lot
// tracking, appropriate for a paper-tracking tool rather than real accounting),
// and what it's worth at that day's market price.
export function computeHoldingsSeries(transactions, priceSeries) {
  const sortedTxns = [...transactions].sort((a, b) => a.date.localeCompare(b.date))
  const sortedPrices = [...priceSeries].sort((a, b) => a.date.localeCompare(b.date))

  let quantityHeld = 0
  let costBasisTotal = 0
  let txnIndex = 0
  const series = []

  function applyTxn(txn) {
    if (txn.side === "buy") {
      costBasisTotal += txn.quantity * txn.price
      quantityHeld += txn.quantity
    } else {
      const avgCost = quantityHeld > 0 ? costBasisTotal / quantityHeld : 0
      costBasisTotal -= avgCost * txn.quantity
      quantityHeld = Math.max(0, quantityHeld - txn.quantity)
    }
  }

  function entryAt(date, price) {
    return { date, quantity: quantityHeld, costBasis: costBasisTotal, marketValue: quantityHeld * price }
  }

  for (const point of sortedPrices) {
    while (txnIndex < sortedTxns.length && sortedTxns[txnIndex].date <= point.date) {
      applyTxn(sortedTxns[txnIndex])
      txnIndex += 1
    }
    series.push(entryAt(point.date, point.price_usd))
  }

  // A purchase dated today (or later, if the price feed hasn't synced yet)
  // has no matching row in priceSeries — mark it to the most recent known
  // price instead of letting it silently vanish from the chart/summary.
  if (txnIndex < sortedTxns.length && sortedPrices.length > 0) {
    const lastPrice = sortedPrices[sortedPrices.length - 1].price_usd
    while (txnIndex < sortedTxns.length) {
      applyTxn(sortedTxns[txnIndex])
      txnIndex += 1
    }
    series.push(entryAt(sortedTxns[sortedTxns.length - 1].date, lastPrice))
  }

  return series
}
