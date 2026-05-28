import { lazy, Suspense } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import LoginPage from './pages/LoginPage'
import TokenGate from './components/TokenGate'
import { useAuth } from './auth/AuthContext'

const HomePage = lazy(() => import('./pages/HomePage'))
const SkillGapPage = lazy(() => import('./pages/SkillGapPage'))
const ProfilePage = lazy(() => import('./pages/ProfilePage'))
const MarketPage = lazy(() => import('./pages/MarketPage'))
const TrendsPage = lazy(() => import('./pages/TrendsPage'))
const CareerPlanPage = lazy(() => import('./pages/CareerPlanPage'))
const DigestHistoryPage = lazy(() => import('./pages/DigestHistoryPage'))
const SearchPage = lazy(() => import('./pages/SearchPage'))
const SubscriptionPage = lazy(() => import('./pages/SubscriptionPage'))
const AccountPage = lazy(() => import('./pages/AccountPage'))
const OrganizationsPage = lazy(() => import('./pages/OrganizationsPage'))
// Sprint-009 TASK-13: shared analysis page (no auth required)
const SharedAnalysisPage = lazy(() => import('./pages/SharedAnalysisPage'))

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? 'text-indigo-600 font-medium' : 'text-gray-600 hover:text-indigo-500'

export default function App() {
  const { logout, mode } = useAuth()

  return (
    <div className="min-h-screen bg-gray-50">
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        {/* Sprint-009 TASK-13: shared analysis — public route, no auth required */}
        <Route
          path="/share/:token"
          element={
            <Suspense fallback={<div className="p-8 text-center text-gray-500">Загружаем...</div>}>
              <SharedAnalysisPage />
            </Suspense>
          }
        />
        <Route
          path="/*"
          element={
            <TokenGate>
              <header className="bg-white shadow-sm">
                <nav className="max-w-5xl mx-auto px-4 py-3 flex gap-6 items-center flex-wrap">
                  <span className="font-bold text-xl text-indigo-600">Skillra</span>
                  <NavLink to="/" className={navLinkClass}>
                    Главная
                  </NavLink>
                  <NavLink to="/skill-gap" className={navLinkClass}>
                    Skill Gap
                  </NavLink>
                  <NavLink to="/market" className={navLinkClass}>
                    Рынок
                  </NavLink>
                  <NavLink to="/trends" className={navLinkClass}>
                    Тренды
                  </NavLink>
                  <NavLink to="/profile" className={navLinkClass}>
                    Профиль
                  </NavLink>
                  <NavLink to="/career-plan" className={navLinkClass}>
                    План
                  </NavLink>
                  <NavLink to="/digest-history" className={navLinkClass}>
                    История
                  </NavLink>
                  <NavLink to="/subscription" className={navLinkClass}>
                    Подписка
                  </NavLink>
                  <NavLink to="/search" className={navLinkClass}>
                    Поиск
                  </NavLink>
                  <NavLink to="/account" className={navLinkClass}>
                    Аккаунт
                  </NavLink>
                  {mode === 'user' && (
                    <NavLink to="/organizations" className={navLinkClass}>
                      Организации
                    </NavLink>
                  )}
                  {mode && (
                    <span className="text-xs text-gray-400">
                      {mode === 'user' ? 'Личный вход' : 'Командный режим'}
                    </span>
                  )}
                  <button
                    onClick={() => {
                      logout()
                      window.location.href = '/login'
                    }}
                    className="ml-auto text-xs text-gray-400 hover:text-red-500"
                  >
                    Выйти
                  </button>
                </nav>
              </header>
              <main className="max-w-5xl mx-auto px-4 py-8">
                <Suspense fallback={<div className="text-sm text-gray-500">Загрузка...</div>}>
                  <Routes>
                    <Route path="/" element={<HomePage />} />
                    <Route path="/skill-gap" element={<SkillGapPage />} />
                    <Route path="/market" element={<MarketPage />} />
                    <Route path="/trends" element={<TrendsPage />} />
                    <Route path="/profile" element={<ProfilePage />} />
                    <Route path="/career-plan" element={<CareerPlanPage />} />
                    <Route path="/digest-history" element={<DigestHistoryPage />} />
                    <Route path="/subscription" element={<SubscriptionPage />} />
                    <Route path="/search" element={<SearchPage />} />
                    <Route path="/account" element={<AccountPage />} />
                    <Route path="/organizations" element={<OrganizationsPage />} />
                  </Routes>
                </Suspense>
              </main>
            </TokenGate>
          }
        />
      </Routes>
    </div>
  )
}
