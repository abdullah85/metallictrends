import { useEffect, useState } from "react"

const STORAGE_KEY = "metallictrends.transactions"

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

// localStorage-backed CRUD for the user's paper buy/sell entries — no backend,
// since there's no login system to attach server-side storage to.
export function useTransactions() {
  const [transactions, setTransactions] = useState(load)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(transactions))
  }, [transactions])

  function addTransaction(txn) {
    setTransactions((prev) => [...prev, { ...txn, id: crypto.randomUUID() }])
  }

  function deleteTransaction(id) {
    setTransactions((prev) => prev.filter((t) => t.id !== id))
  }

  function replaceAll(newTransactions) {
    setTransactions(newTransactions)
  }

  return { transactions, addTransaction, deleteTransaction, replaceAll }
}
