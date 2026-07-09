export default function TransactionTable({ transactions, onDelete }) {
  if (transactions.length === 0) return <p className="pf-empty">No transactions yet.</p>

  const sorted = [...transactions].sort((a, b) => a.date.localeCompare(b.date))

  return (
    <table className="pf-table">
      <thead>
        <tr>
          <th>Date</th>
          <th>Metal</th>
          <th>Side</th>
          <th>Quantity</th>
          <th>Price</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {sorted.map((t) => (
          <tr key={t.id}>
            <td>{t.date}</td>
            <td className="pf-cap">{t.metal}</td>
            <td className="pf-cap">{t.side}</td>
            <td>{t.quantity}</td>
            <td>${t.price.toFixed(2)}</td>
            <td>
              <button type="button" className="pf-btn-danger" onClick={() => onDelete(t.id)}>Delete</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
