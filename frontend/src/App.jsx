import { useEffect, useState } from "react"
import { METALS } from "./api.js"
import { useTransactions } from "./hooks/useTransactions.js"
import MetalSelector from "./components/MetalSelector.jsx"
import PriceChart from "./components/PriceChart.jsx"
import TransactionForm from "./components/TransactionForm.jsx"
import TransactionTable from "./components/TransactionTable.jsx"
import CsvControls from "./components/CsvControls.jsx"
import PerformanceChart from "./components/PerformanceChart.jsx"
import { METAL_TICKER, capitalize } from "./theme.js"

const isEmbedded = window.self !== window.top

function initialMetal() {
  const requested = new URLSearchParams(window.location.search).get("metal")
  return METALS.includes(requested) ? requested : "gold"
}

function App() {
  const [selectedMetal, setSelectedMetal] = useState(initialMetal)
  const [prefill, setPrefill] = useState(null)
  const { transactions, addTransaction, deleteTransaction, replaceAll } = useTransactions()

  // Prefill is only ever meaningful for the metal it was captured from —
  // switching tabs abandons any in-progress "click to log" flow.
  useEffect(() => {
    setPrefill(null)
  }, [selectedMetal])

  // Keep the URL in sync so a direct visit to /portfolio/?metal=silver (or a
  // reload while embedded) lands back on the metal the user was looking at.
  useEffect(() => {
    const url = new URL(window.location.href)
    url.searchParams.set("metal", selectedMetal)
    window.history.replaceState(null, "", url)
  }, [selectedMetal])

  // The landing page can only trap Escape while focus stays in its own
  // document; once focus moves into this iframe, the parent never sees the
  // keydown. Forward it so the host page's modal can still close on Escape.
  useEffect(() => {
    if (!isEmbedded) return
    const onKeyDown = (e) => {
      if (e.key === "Escape") {
        window.parent.postMessage({ source: "metallictrends-portfolio", type: "close" }, window.location.origin)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])

  return (
    <div className={`pf-shell${isEmbedded ? " pf-shell--embedded" : ""}`}>
      {!isEmbedded && (
        <>
          <div className="pf-eyebrow">Interactive · updated daily</div>
          <h1>MetallicTrends Portfolio</h1>
        </>
      )}
      <MetalSelector metals={METALS} selected={selectedMetal} onChange={setSelectedMetal} />

      <section className="pf-card">
        <h2>
          {capitalize(selectedMetal)} price history
          <span className="pf-ticker" style={{ "--metal-color": `var(--c-${selectedMetal})` }}>
            {METAL_TICKER[selectedMetal]}
          </span>
        </h2>
        <PriceChart metal={selectedMetal} range={{ days: 365 }} onPointClick={setPrefill} />
      </section>

      <section className="pf-card">
        <h2>Transactions</h2>
        <TransactionForm metal={selectedMetal} onAdd={addTransaction} prefill={prefill} onConsumePrefill={() => setPrefill(null)} />
        <CsvControls transactions={transactions} onImport={replaceAll} />
        <TransactionTable transactions={transactions} onDelete={deleteTransaction} />
      </section>

      <section className="pf-card">
        <h2>
          {capitalize(selectedMetal)} performance
          <span className="pf-ticker" style={{ "--metal-color": `var(--c-${selectedMetal})` }}>
            {METAL_TICKER[selectedMetal]}
          </span>
        </h2>
        <PerformanceChart metal={selectedMetal} transactions={transactions} />
      </section>
    </div>
  )
}

export default App
