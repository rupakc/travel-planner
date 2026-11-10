import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Plane, Calendar, Globe, DollarSign, Pencil, Minus, Plus, X, BadgeCheck, MapPin, Sparkles,
  ImageIcon, ScanText, AlertTriangle,
} from 'lucide-react'
import AirportSearch from '../ui/AirportSearch'
import NationalitySearch from '../ui/NationalitySearch'
import TravelerPanel from '../ui/TravelerPanel'
import ImportMap from './ImportMap'
import { kindOf } from './kinds'
import { safeUrl } from '../../utils/planPrint'
import { resolveImportPlace } from '../../services/api'
import { importErrorView } from '../../utils/linkImport'
import { MAX_MUST_INCLUDE, buildImportSearch, defaultImportDates, previewToDraft } from '../../utils/linkImport'
import { fmtDate as formatDate } from '../../i18n/format'

const shortCity = (name) => (name || '').split(',')[0]
const fmtDate = (iso) => {
  const [y, m, d] = iso.split('-').map(Number)
  return formatDate(new Date(Date.UTC(y, m - 1, d)), { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' })
}
const addDays = (iso, n) => {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10)
}

function SourceCard({ source, placeCount }) {
  const { t } = useTranslation('search')
  const href = safeUrl(source.url)
  const [iconOk, setIconOk] = useState(true)
  const icon = safeUrl(source.favicon_url)
  const Fallback = source.kind === 'images' ? ImageIcon : ScanText
  const heading = source.kind === 'url'
    ? source.title || source.site_name || t('preview.pageShared')
    : source.kind === 'images' ? t('preview.yourShots') : t('preview.yourText')
  return (
    <div className="flex items-start gap-3 rounded-xl bg-white/80 p-3 ring-1 ring-amber-200/80">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-amber-50 ring-1 ring-amber-200">
        {icon && iconOk
          ? <img src={icon} alt="" className="h-5 w-5" onError={() => setIconOk(false)} />
          : <Fallback size={18} className="text-amber-700" />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-gray-900">
          {href
            ? <a href={href} target="_blank" rel="noopener noreferrer" className="hover:underline decoration-amber-400 decoration-2 underline-offset-2">{heading}</a>
            : heading}
        </p>
        <p className="truncate text-xs text-gray-500">
          {t('preview.sourceFound', {
            meta: [source.site_name, source.author && t('preview.by', { author: source.author })].filter(Boolean).join(', ') || t('preview.readJustNow'),
            count: placeCount,
          })}
        </p>
      </div>
    </div>
  )
}

function PlaceRow({ place, number, stops, onChange }) {
  const { t } = useTranslation('search')
  const [editing, setEditing] = useState(false)
  const [draftName, setDraftName] = useState(place.name)
  const { icon: Icon, color, labelKey } = kindOf(place.kind)
  const label = t(labelKey)
  const save = () => {
    const name = draftName.trim()
    if (name) onChange({ name })
    else setDraftName(place.name)
    setEditing(false)
  }
  const town = place.city && shortCity(place.destination) !== place.city ? place.city : null
  return (
    <li className={`flex gap-3 py-3 transition-opacity ${place.selected ? '' : 'opacity-55'}`}>
      <input type="checkbox" checked={place.selected} onChange={() => onChange({ selected: !place.selected })}
        aria-label={t('preview.includeAria', { name: place.name })} data-tid="search.import-place-include"
        className="mt-1 h-4 w-4 shrink-0 cursor-pointer rounded border-gray-300 accent-teal-600" />
      <span aria-hidden="true" className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
        style={place.approximate ? { color, boxShadow: `inset 0 0 0 2px ${color}` } : { background: color, color: 'rgb(var(--c-white))' }}>
        {number}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Icon size={14} style={{ color }} aria-label={label} className="shrink-0" />
          {editing ? (
            <input autoFocus value={draftName} aria-label={t('preview.newNameAria', { name: place.name })} data-tid="search.import-place-name"
              onChange={(e) => setDraftName(e.target.value)}
              onBlur={save}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { e.preventDefault(); save() }
                if (e.key === 'Escape') { e.stopPropagation(); setDraftName(place.name); setEditing(false) }
              }}
              className="min-w-0 flex-1 rounded-md border border-amber-300 px-2 py-0.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-300" />
          ) : (
            <span className="text-sm font-semibold text-gray-900">{place.name}</span>
          )}
          {!editing && (
            <button type="button" onClick={() => { setDraftName(place.name); setEditing(true) }} aria-label={t('preview.renameAria', { name: place.name })} data-tid="search.import-place-rename"
              className="rounded p-0.5 text-gray-300 hover:text-gray-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400">
              <Pencil size={12} />
            </button>
          )}
          {town && <span className="text-xs text-gray-500">{t('preview.dayTrip', { town })}</span>}
          {place.verified
            ? <span className="inline-flex items-center gap-0.5 text-[11px] text-emerald-700" title={place.address || t('preview.foundOnGoogle')}><BadgeCheck size={12} />{t('preview.onMap')}{place.rating ? t('preview.rating', { rating: place.rating }) : ''}</span>
            : <span className="text-[11px] text-gray-400" title={t('preview.approximateTitle')}>{t('preview.approximate')}</span>}
        </div>
        {place.quote && (
          <p className="mt-1 text-sm italic text-stone-700">
            <span className="bg-gradient-to-t from-amber-200/80 from-45% to-transparent to-45% px-0.5">“{place.quote}”</span>
          </p>
        )}
        {place.note && <p className="mt-0.5 text-xs text-gray-500">{place.note}</p>}
        {stops.length > 1 && (
          <label className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-gray-500">
            <MapPin size={11} aria-hidden="true" />
            <span>{t('preview.stop')}</span>
            <select value={place.destination || ''} onChange={(e) => onChange({ destination: e.target.value })}
              aria-label={t('preview.stopFor', { name: place.name })} data-tid="search.import-place-stop"
              className="rounded-md border border-gray-200 bg-white py-0.5 pl-2 pr-7 text-xs text-gray-700 hover:border-gray-300 focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-300">
              {stops.map((s) => <option key={s.name} value={s.name}>{shortCity(s.name)}</option>)}
            </select>
          </label>
        )}
      </div>
    </li>
  )
}

function UnresolvedRow({ place, stops, token, onPick, onPlaced }) {
  const { t } = useTranslation('search')
  const [town, setTown] = useState(place.city || '')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const placeIt = async () => {
    if (!town.trim() || busy) return
    setBusy(true)
    setProblem(null)
    try {
      const resolved = await resolveImportPlace({
        id: place.id, name: place.name, kind: place.kind, city: town.trim(),
        note: place.note || null, quote: place.quote || null,
      }, token)
      const refusal = onPlaced(resolved)
      if (refusal) setProblem(refusal)
    } catch (err) {
      setProblem(importErrorView(err)?.message || t('preview.placeFailed'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <li className="space-y-1.5 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-gray-800">{place.name}</span>
        <span className="ml-auto flex items-center gap-1.5">
          <input value={town} onChange={(e) => setTown(e.target.value)} aria-label={t('preview.townFor', { name: place.name })} data-tid="search.import-town"
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); placeIt() } }}
            placeholder={t('preview.whichTown')}
            className="w-36 rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-300" />
          <button type="button" onClick={placeIt} disabled={!town.trim() || busy} data-tid="search.import-place-it"
            className="rounded-lg bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-900 ring-1 ring-amber-200 hover:bg-amber-200 disabled:opacity-50">
            {busy ? t('preview.placing') : t('preview.placeIt')}
          </button>
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-1.5 text-xs text-gray-500">
        {t('preview.orAddTo')}
        <select value={place.destination || ''} aria-label={t('preview.whichStop', { name: place.name })} data-tid="search.import-unplaced-stop"
          onChange={(e) => onPick(e.target.value || null)}
          className="rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-amber-300">
          <option value="">{t('preview.leaveOut')}</option>
          {stops.map((s) => <option key={s.name} value={s.name}>{shortCity(s.name)}</option>)}
        </select>
      </div>
      {problem && <p role="alert" className="text-xs text-rose-700">{problem}</p>}
    </li>
  )
}

/**
 * "Here's what we found": the imported places on a map and in a review list
 * (tick, rename, move between stops, place the unplaced), the route with
 * nights per stop, and the usual trip fields. onPlan({form, stops,
 * placeCount}) hands the result to the Search page's normal search.
 */
export default function ImportPreview({ preview, form, today, token, onPlan, onStartOver }) {
  const { t } = useTranslation('search')
  const [draft, setDraft] = useState(() => previewToDraft(preview))
  const [trip, setTrip] = useState(() => ({
    ...form,
    departure_date: defaultImportDates(today, preview.suggested_days).departure_date,
  }))

  const includedStops = draft.stops.filter((s) => s.included)
  const nights = includedStops.reduce((n, s) => n + Math.max(1, s.nights || 1), 0)
  const built = useMemo(() => buildImportSearch({ form: trip, preview, draft }), [trip, preview, draft])
  const placeCount = built.form.must_include.length
  const selectedTotal = [...draft.places, ...draft.unresolved]
    .filter((p) => p.selected && p.destination && includedStops.some((s) => s.name === p.destination)).length

  // Map pins: numbered in list order; only ticked places in included stops
  const numbered = draft.places.map((p, i) => ({ ...p, number: i + 1 }))
  const pins = numbered.filter((p) => p.selected && includedStops.some((s) => s.name === p.destination))

  const updatePlace = (id, patch) => setDraft((d) => ({
    ...d,
    places: d.places.map((p) => (p.id === id ? { ...p, ...patch } : p)),
    unresolved: d.unresolved.map((p) => (p.id === id ? { ...p, ...patch } : p)),
  }))
  const selectStop = (name, selected) => setDraft((d) => ({
    ...d, places: d.places.map((p) => (p.destination === name ? { ...p, selected } : p)),
  }))
  // A spot placed by the town the traveller typed: into its stop, or as a
  // new stop while the route has room. Returns a message when it can't.
  const placeResolved = ({ place, destination }) => {
    const known = draft.stops.some((s) => s.name === destination.name)
    if (!known && draft.stops.length >= 3) {
      return t('preview.tooManyStops', { city: shortCity(destination.name) })
    }
    setDraft((d) => ({
      ...d,
      stops: known ? d.stops : [...d.stops, { ...destination, included: true }],
      unresolved: d.unresolved.filter((p) => p.id !== place.id),
      places: [...d.places, { ...place, selected: true }],
    }))
    return null
  }
  const updateStop = (name, patch) => setDraft((d) => ({
    ...d, stops: d.stops.map((s) => (s.name === name ? { ...s, ...patch } : s)),
  }))

  const missing = !trip.origin?.trim() ? t('preview.missingOrigin') : !trip.nationality?.trim() ? t('preview.missingNationality') : null
  const canPlan = !missing && placeCount > 0 && includedStops.length > 0 && trip.departure_date >= today

  const plan = (e) => {
    e.preventDefault()
    if (!canPlan) return
    onPlan({ form: built.form, stops: built.stops, placeCount })
  }

  const inputClass = 'w-full px-3 py-2.5 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 focus:border-teal-400 text-sm bg-white'
  const labelClass = 'block text-sm font-medium text-gray-700 mb-1'
  const sourcePlaceCount = draft.places.length + draft.unresolved.length

  return (
    <form onSubmit={plan} className="space-y-6" aria-labelledby="import-preview-title">
      {/* What we found */}
      <div className="rounded-2xl bg-gradient-to-br from-amber-50 via-orange-50/60 to-white p-4 ring-1 ring-amber-200/70 sm:p-5">
        <p className="mb-3 text-sm font-medium text-amber-800">{t('preview.found')}</p>
        <h2 id="import-preview-title" className="font-display text-2xl font-bold tracking-tight text-gray-900 sm:text-3xl">{preview.title}</h2>
        {preview.summary && <p className="mt-1 max-w-prose text-sm text-gray-600">{preview.summary}</p>}
        <div className="mt-4"><SourceCard source={preview.source || {}} placeCount={sourcePlaceCount} /></div>
      </div>

      <ImportMap places={pins} />

      {/* Route: stops with nights */}
      <div>
        <p className={labelClass}>{t('preview.route')}</p>
        <ul className="flex flex-wrap items-center gap-2">
          {draft.stops.map((s, i) => (
            <li key={s.name} className="flex items-center gap-2">
              {i > 0 && <span aria-hidden="true" className="text-gray-300">→</span>}
              <span className={`flex items-center gap-1 rounded-full py-1 pl-3 pr-1 text-sm ring-1 ${s.included ? 'bg-teal-50 text-teal-900 ring-teal-200' : 'bg-gray-50 text-gray-400 ring-gray-200 line-through'}`}>
                <span className="font-medium">{shortCity(s.name)}</span>
                {s.included && (
                  <span className="ml-1 flex items-center rounded-full bg-white ring-1 ring-teal-200">
                    <button type="button" aria-label={t('preview.oneLess', { city: shortCity(s.name) })} data-tid="search.import-night-minus" disabled={s.nights <= 1}
                      onClick={() => updateStop(s.name, { nights: Math.max(1, s.nights - 1) })}
                      className="rounded-full p-1 text-teal-700 hover:bg-teal-100 disabled:opacity-30"><Minus size={12} /></button>
                    <span className="min-w-[4.5rem] text-center text-xs tabular-nums">{t('preview.nights', { count: s.nights })}</span>
                    <button type="button" aria-label={t('preview.oneMore', { city: shortCity(s.name) })} data-tid="search.import-night-plus" disabled={s.nights >= 21}
                      onClick={() => updateStop(s.name, { nights: Math.min(21, s.nights + 1) })}
                      className="rounded-full p-1 text-teal-700 hover:bg-teal-100 disabled:opacity-30"><Plus size={12} /></button>
                  </span>
                )}
                {draft.stops.length > 1 && (
                  <button type="button" onClick={() => updateStop(s.name, { included: !s.included })}
                    aria-label={s.included ? t('preview.leaveOutStop', { city: shortCity(s.name) }) : t('preview.addBack', { city: shortCity(s.name) })} data-tid="search.import-stop-toggle"
                    className="rounded-full p-1 text-gray-400 hover:bg-white hover:text-gray-700">
                    {s.included ? <X size={12} /> : <Plus size={12} />}
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-1.5 text-xs text-gray-500">
          {preview.suggested_days
            ? t('preview.totalWithHint', { total: t('preview.totalNights', { count: nights }), hint: t('preview.suggestedDays', { count: preview.suggested_days }) })
            : t('preview.totalPlain', { total: t('preview.totalNights', { count: nights }) })}
          {preview.season_hint ? ` ${t('preview.bestTime', { season: preview.season_hint })}` : ''}
        </p>
      </div>

      {/* Places by stop */}
      <div className="space-y-5">
        {draft.stops.filter((s) => s.included).map((stop) => {
          const rows = numbered.filter((p) => p.destination === stop.name)
          if (!rows.length) return null
          const city = shortCity(stop.name)
          return (
            <section key={stop.name} aria-label={t('preview.placesIn', { city })}>
              <div className="flex items-baseline justify-between gap-2 border-b border-gray-100 pb-1">
                <h3 className="text-base font-semibold text-gray-900">{city}<span className="ml-2 text-xs font-normal text-gray-400">{stop.country}</span></h3>
                <span className="text-xs text-gray-500">
                  <button type="button" aria-label={t('preview.selectAll', { city })} data-tid="search.import-select-all" onClick={() => selectStop(stop.name, true)} className="hover:text-teal-700 hover:underline">{t('preview.all')}</button>
                  {' / '}
                  <button type="button" aria-label={t('preview.selectNone', { city })} data-tid="search.import-select-none" onClick={() => selectStop(stop.name, false)} className="hover:text-teal-700 hover:underline">{t('preview.none')}</button>
                </span>
              </div>
              <ul className="divide-y divide-gray-50">
                {rows.map((p) => (
                  <PlaceRow key={p.id} place={p} number={p.number} stops={includedStops} onChange={(patch) => updatePlace(p.id, patch)} />
                ))}
              </ul>
            </section>
          )
        })}

        {draft.unresolved.length > 0 && (
          <section aria-label={t('preview.unplacedAria')} className="rounded-xl border border-dashed border-gray-300 p-3">
            <h3 className="text-sm font-semibold text-gray-700">{t('preview.unplaced', { count: draft.unresolved.length })}</h3>
            <p className="text-xs text-gray-500">{t('preview.unplacedHint')}</p>
            <ul className="mt-2 space-y-3">
              {draft.unresolved.map((p) => (
                <UnresolvedRow key={p.id} place={p} stops={includedStops} token={token}
                  onPick={(destination) => updatePlace(p.id, { destination })}
                  onPlaced={placeResolved} />
              ))}
            </ul>
          </section>
        )}

        {(preview.warnings || []).filter((w) => !w.startsWith("We couldn't place")).map((w) => (
          <p key={w} className="flex items-start gap-2 text-xs text-amber-800"><AlertTriangle size={13} className="mt-0.5 shrink-0" />{w}</p>
        ))}
      </div>

      {/* The usual trip fields */}
      <div className="space-y-4 rounded-2xl bg-gray-50/80 p-4 ring-1 ring-gray-100 sm:p-5">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <AirportSearch label={<span className="inline-flex items-center gap-1.5"><Plane size={13} /> {t('form.from')}</span>}
            value={trip.origin} onChange={(v) => setTrip((t) => ({ ...t, origin: v }))} placeholder={t('form.cityOrAirport')} required />
          <div>
            <label className={labelClass} htmlFor="import-departure"><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> {t('preview.leavingOn')}</span></label>
            <input id="import-departure" type="date" required value={trip.departure_date} min={today}
              onChange={(e) => setTrip((t) => ({ ...t, departure_date: e.target.value }))} className={inputClass} />
            {trip.departure_date && <p className="mt-1 text-xs text-gray-500">{t('preview.back', { date: fmtDate(addDays(trip.departure_date, nights)) })}</p>}
          </div>
        </div>
        <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-3">
          <NationalitySearch label={<span className="inline-flex items-center gap-1.5"><Globe size={13} /> {t('form.nationality')}</span>}
            value={trip.nationality} onChange={(v) => setTrip((t) => ({ ...t, nationality: v }))} placeholder={t('form.nationalityPlaceholder')} />
          <div>
            <label className={labelClass} htmlFor="import-budget"><span className="inline-flex items-center gap-1.5"><DollarSign size={13} /> {t('form.budget')}</span></label>
            <input id="import-budget" type="number" min="0" step="100" value={trip.budget_usd ?? ''} placeholder={t('form.totalBudget')}
              onChange={(e) => setTrip((t) => ({ ...t, budget_usd: e.target.value }))} className={inputClass} />
          </div>
          <TravelerPanel form={trip} setForm={setTrip} />
        </div>
        {built.form.interests.length > 0 && (
          <p className="text-xs text-gray-500">{t('preview.interests', { list: built.form.interests.map(i => t(`interestNames.${i}`, { defaultValue: i })).join(', ') })}</p>
        )}
      </div>

      <div className="space-y-2">
        {missing && <p className="text-sm text-amber-800">{missing}</p>}
        {!missing && placeCount === 0 && <p className="text-sm text-amber-800">{t('preview.tickOne')}</p>}
        {selectedTotal > MAX_MUST_INCLUDE && (
          <p className="text-xs text-gray-500">{t('preview.capNote', { max: MAX_MUST_INCLUDE })}</p>
        )}
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          <button type="button" onClick={onStartOver} data-tid="search.import-start-over"
            className="rounded-xl px-5 py-3 text-sm font-medium text-gray-600 ring-1 ring-gray-200 hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400">
            {t('preview.startOver')}
          </button>
          <button type="submit" disabled={!canPlan} data-tid="search.import-plan"
            className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-600 to-teal-700 px-6 py-3.5 text-base font-semibold text-white shadow-lg transition-all hover:from-teal-700 hover:to-teal-800 hover:shadow-xl active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none">
            <Sparkles size={18} /> {t('preview.plan', { count: placeCount })}
          </button>
        </div>
      </div>
    </form>
  )
}
