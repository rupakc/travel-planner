import { Trans, useTranslation } from 'react-i18next'
import { openPrivacyChoices } from '../ConsentPrompt'

const linkClass = 'underline hover:text-gray-600'

// Source names (GeoNames, OurAirports) and the licence name stay as they are
// in every language; the GeoNames credit is a CC BY 4.0 requirement.
const ExternalLink = ({ href, tid, children }) => (
  <a href={href} target="_blank" rel="noopener noreferrer" className={linkClass} data-tid={tid}>{children}</a>
)

// Shown on every page (the signed-in layout, login, share, change password).
// "Privacy choices" reopens the consent sheet, so signed-out visitors can
// switch telemetry off too.
export default function AttributionFooter() {
  const { t } = useTranslation('privacy')
  return (
    <footer className="py-4 text-center text-xs text-gray-500 print:hidden">
      <Trans
        ns="common"
        i18nKey="footer.attribution"
        components={{
          geonames: <ExternalLink href="https://www.geonames.org/" tid="footer.geonames" />,
          licence: <ExternalLink href="https://creativecommons.org/licenses/by/4.0/" tid="footer.licence" />,
          ourairports: <ExternalLink href="https://ourairports.com/" tid="footer.ourairports" />,
        }}
      />
      <span aria-hidden="true"> · </span>
      <button type="button" onClick={openPrivacyChoices} className={linkClass} data-tid="privacy.choices">
        {t('choices')}
      </button>
    </footer>
  )
}
