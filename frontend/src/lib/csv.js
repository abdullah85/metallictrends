// Hand-rolled CSV — the schema is flat (5 plain fields, no embedded commas or
// quotes possible), so a parsing library would be more machinery than the data needs.
const HEADER = ["date", "metal", "side", "quantity", "price"]

export function transactionsToCsv(transactions) {
  const lines = [HEADER.join(",")]
  for (const t of transactions) {
    lines.push([t.date, t.metal, t.side, t.quantity, t.price].join(","))
  }
  return lines.join("\n")
}

export function csvToTransactions(text) {
  const lines = text.trim().split(/\r?\n/)
  const [header, ...rows] = lines
  const cols = header.split(",").map((c) => c.trim().toLowerCase())

  return rows
    .filter((line) => line.trim() !== "")
    .map((line) => {
      const values = line.split(",")
      const row = Object.fromEntries(cols.map((c, i) => [c, values[i]?.trim()]))
      return {
        id: crypto.randomUUID(),
        date: row.date,
        metal: row.metal,
        side: row.side,
        quantity: Number(row.quantity),
        price: Number(row.price),
      }
    })
}
