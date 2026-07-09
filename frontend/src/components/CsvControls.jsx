import { useRef } from "react"
import { csvToTransactions, transactionsToCsv } from "../lib/csv.js"

export default function CsvControls({ transactions, onImport }) {
  const fileInputRef = useRef(null)

  function handleExport() {
    const csv = transactionsToCsv(transactions)
    const blob = new Blob([csv], { type: "text/csv" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = "metallictrends-transactions.csv"
    a.click()
    URL.revokeObjectURL(url)
  }

  function handleFileChange(e) {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      onImport(csvToTransactions(String(reader.result)))
    }
    reader.readAsText(file)
    e.target.value = "" // allow re-importing the same filename later
  }

  return (
    <div className="pf-csv-row">
      <button type="button" className="pf-btn pf-btn-ghost" onClick={handleExport}>Export CSV</button>
      <button type="button" className="pf-btn pf-btn-ghost" onClick={() => fileInputRef.current?.click()}>Import CSV</button>
      <input
        type="file"
        accept=".csv,text/csv"
        ref={fileInputRef}
        onChange={handleFileChange}
        style={{ display: "none" }}
      />
    </div>
  )
}
