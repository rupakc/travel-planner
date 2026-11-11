import { createContext, useContext, useState, useCallback } from 'react'

const SearchDataContext = createContext(null)

export function SearchDataProvider({ children }) {
  const [pendingSearchData, setPendingSearchData] = useState(null)
  const [hasSearchResults, setHasSearchResults] = useState(false)
  const clearPendingSearch = useCallback(() => setPendingSearchData(null), [])
  const showResults = useCallback(() => setHasSearchResults(true), [])
  const clearSearchResults = useCallback(() => setHasSearchResults(false), [])
  // A saved plan to open in the planner ("Open in planner" on a trip): the
  // Results page loads it once its search starts, then clears it.
  const [pendingPlan, setPendingPlanState] = useState(null)
  const setPendingPlan = useCallback((plan) => setPendingPlanState(plan ?? null), [])
  const clearPendingPlan = useCallback(() => setPendingPlanState(null), [])
  return (
    <SearchDataContext.Provider value={{
      pendingSearchData, setPendingSearchData, clearPendingSearch, hasSearchResults, showResults, clearSearchResults,
      pendingPlan, setPendingPlan, clearPendingPlan,
    }}>
      {children}
    </SearchDataContext.Provider>
  )
}

export function useSearchData() {
  const ctx = useContext(SearchDataContext)
  if (!ctx) throw new Error('useSearchData must be used inside SearchDataProvider')
  return ctx
}
