const linkClass = 'underline hover:text-gray-600'

export default function AttributionFooter() {
  return (
    <footer className="py-4 text-center text-xs text-gray-400 print:hidden">
      Place data © <a href="https://www.geonames.org/" target="_blank" rel="noopener noreferrer" className={linkClass}>GeoNames</a>{' '}
      (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer" className={linkClass}>CC BY 4.0</a>)
      {' · '}Airport data: <a href="https://ourairports.com/" target="_blank" rel="noopener noreferrer" className={linkClass}>OurAirports</a>
    </footer>
  )
}
