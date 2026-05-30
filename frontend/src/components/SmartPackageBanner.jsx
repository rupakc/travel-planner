import { X, Plane, Hotel, MapPin, Smartphone } from 'lucide-react'

export default function SmartPackageBanner({ packageData, onAccept, onDismiss }) {
  if (!packageData) return null

  const {
    flight,
    hotel,
    activities = [],
    sim,
    total_cost_usd,
    savings_vs_expensive,
  } = packageData

  return (
    <div className="relative w-full rounded-xl overflow-hidden">
      {/* Gradient background */}
      <div
        className="px-5 py-4"
        style={{
          background: 'linear-gradient(135deg, #0d9488 0%, #4f46e5 100%)',
        }}
      >
        {/* Top-right: badge + dismiss */}
        <div className="absolute top-3 right-3 flex items-center gap-2">
          <span className="bg-white text-teal-700 text-xs font-semibold px-2.5 py-0.5 rounded-full shadow-sm">
            Best Value Package
          </span>
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="text-white/70 hover:text-white transition-colors"
              aria-label="Dismiss"
            >
              <X size={16} />
            </button>
          )}
        </div>

        {/* Package details */}
        <div className="pr-36 space-y-3">
          <div className="grid grid-cols-2 gap-x-6 gap-y-2">
            {/* Flight */}
            {flight && (
              <div className="flex items-center gap-2 min-w-0">
                <Plane size={14} className="text-white/70 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-xs text-white/60 leading-none">Flight</p>
                  <p className="text-sm font-semibold text-white truncate">
                    {flight.airline}
                    {flight.price_usd != null && (
                      <span className="font-normal text-white/80 ml-1">
                        ${flight.price_usd.toLocaleString()}
                      </span>
                    )}
                  </p>
                </div>
              </div>
            )}

            {/* Hotel */}
            {hotel && (
              <div className="flex items-center gap-2 min-w-0">
                <Hotel size={14} className="text-white/70 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-xs text-white/60 leading-none">Hotel</p>
                  <p className="text-sm font-semibold text-white truncate">
                    {hotel.name}
                    {hotel.tier && (
                      <span className="font-normal text-white/70 ml-1 capitalize">
                        · {hotel.tier}
                      </span>
                    )}
                  </p>
                </div>
              </div>
            )}

            {/* Activities */}
            {activities.length > 0 && (
              <div className="flex items-center gap-2">
                <MapPin size={14} className="text-white/70 flex-shrink-0" />
                <div>
                  <p className="text-xs text-white/60 leading-none">Activities</p>
                  <p className="text-sm font-semibold text-white">
                    {activities.length} included
                  </p>
                </div>
              </div>
            )}

            {/* SIM */}
            {sim && (
              <div className="flex items-center gap-2 min-w-0">
                <Smartphone size={14} className="text-white/70 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-xs text-white/60 leading-none">SIM</p>
                  <p className="text-sm font-semibold text-white truncate">
                    {sim.name ?? 'Included'}
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Total + savings */}
          <div className="flex items-end gap-4 pt-1">
            {total_cost_usd != null && (
              <div>
                <p className="text-xs text-white/60">Total cost</p>
                <p className="text-xl font-bold text-white">
                  ${total_cost_usd.toLocaleString()}
                </p>
              </div>
            )}
            {savings_vs_expensive > 0 && (
              <p className="text-sm font-medium text-emerald-300 pb-0.5">
                Save ${savings_vs_expensive.toLocaleString()} vs luxury option
              </p>
            )}
          </div>
        </div>

        {/* Accept button */}
        <div className="mt-4">
          <button
            onClick={() => onAccept && onAccept(packageData)}
            className="bg-white text-teal-700 font-semibold text-sm px-5 py-2 rounded-lg hover:bg-teal-50 transition-colors shadow-sm"
          >
            Accept Package
          </button>
        </div>
      </div>
    </div>
  )
}
