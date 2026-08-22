import { useTranslation } from 'react-i18next'

/**
 * Signed in, but attached to no school.
 *
 * A real state rather than an error: Google let the person in, an
 * administrator simply has not written their address down yet. Every section
 * would answer 403 for them, so instead of five identical refusals they get
 * one screen that says what to do — and the address to pass on, since that is
 * exactly what the administrator needs to type.
 */
export default function NoSchool({ user, onLoggedOut }) {
  const { t } = useTranslation()

  return (
    <main className="page narrow">
      <header className="page-header">
        <h1>{t('noSchool.title')}</h1>
      </header>

      <section className="panel">
        <p className="hint">{t('noSchool.hint')}</p>
        {user?.email && (
          <p>
            <strong>{user.email}</strong>
          </p>
        )}
        <div className="actions">
          <button type="button" className="secondary" onClick={onLoggedOut}>
            {t('nav.logout')}
          </button>
        </div>
      </section>
    </main>
  )
}
