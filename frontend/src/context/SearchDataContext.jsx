import { createContext, useContext, useState, useCallback } from 'react'

const SearchDataContext = createContext(null)

export function SearchDataProvider({ children }) {
  const [pendingSearchData, setPendingSearchData] = useState(null)
  const [hasSearchResults, setHasSearchResults] = useState(false)
  const clearPendingSearch = useCallback(() => setPendingSearchData(null), [])
  const showResults = useCallback(() => setHasSearchResults(true), [])
  const clearSearchResults = useCallback(() => setHasSearchResults(false), [])
  return (
    <SearchDataContext.Provider value={{ pendingSearchData, setPendingSearchData, clearPendingSearch, hasSearchResults, showResults, clearSearchResults }}>
      {children}
    </SearchDataContext.Provider>
  )
}

export function useSearchData() {
  const ctx = useContext(SearchDataContext)
  if (!ctx) throw new Error('useSearchData must be used inside SearchDataProvider')
  return ctx
}
