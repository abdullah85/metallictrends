import { useEffect, useRef, useState } from "react"
import { usePriceOnDate } from "../hooks/usePriceOnDate.js"

const emptyFields = { date: "", side: "buy", quantity: "", price: "" }

export default function TransactionForm({ metal, onAdd, prefill, onConsumePrefill }) {
  const [form, setForm] = useState(emptyFields)
  const defaultPrice = usePriceOnDate(metal, form.date)
  const quantityRef = useRef(null)

  // Re-fill the price field whenever the picked date resolves to a known
  // market price. Runs only when `defaultPrice` changes (i.e. date or metal
  // changed) — typing in the price field afterwards doesn't retrigger it.
  useEffect(() => {
    if (defaultPrice != null) {
      setForm((prev) => ({ ...prev, price: String(defaultPrice) }))
    }
  }, [defaultPrice])

  // Clicking a point on the price chart fills in the date + exact price for
  // that day — the user only has to type a quantity and confirm.
  useEffect(() => {
    if (!prefill) return
    setForm((prev) => ({ ...prev, date: prefill.date, price: String(prefill.price) }))
    quantityRef.current?.focus()
  }, [prefill])

  function handleChange(e) {
    const { name, value } = e.target
    setForm((prev) => ({ ...prev, [name]: value }))
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (!form.date || !form.quantity || !form.price) return
    onAdd({
      date: form.date,
      metal,
      side: form.side,
      quantity: Number(form.quantity),
      price: Number(form.price),
    })
    setForm(emptyFields)
    onConsumePrefill?.()
  }

  return (
    <>
      {prefill && (
        <p className="pf-prefill-hint">
          Logging a purchase on {prefill.date} at ${prefill.price.toFixed(2)}/oz — just add the quantity.{" "}
          <button type="button" className="pf-link" onClick={() => { setForm(emptyFields); onConsumePrefill?.() }}>
            Cancel
          </button>
        </p>
      )}
      <form onSubmit={handleSubmit} className="pf-form">
        <label className="pf-field">
          Date
          <input type="date" name="date" value={form.date} onChange={handleChange} required />
        </label>
        <label className="pf-field">
          Side
          <select name="side" value={form.side} onChange={handleChange}>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </label>
        <label className="pf-field">
          Quantity (oz)
          <input
            ref={quantityRef}
            type="number"
            name="quantity"
            value={form.quantity}
            onChange={handleChange}
            step="any"
            min="0"
            required
          />
        </label>
        <label className="pf-field">
          Price (USD/oz)
          <input type="number" name="price" value={form.price} onChange={handleChange} step="any" min="0" required />
        </label>
        <button type="submit" className="pf-btn pf-btn-primary">Add</button>
      </form>
    </>
  )
}
