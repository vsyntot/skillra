import { Link } from 'react-router-dom'
import { commercialLockedMessage } from './commercial'

export default function LockedFeatureCallout({ feature }: { feature: string }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <p>{commercialLockedMessage(feature)}</p>
      <Link to="/account" className="mt-2 inline-flex font-medium text-amber-950 underline underline-offset-2">
        Открыть аккаунт
      </Link>
    </div>
  )
}
