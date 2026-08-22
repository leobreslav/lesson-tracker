import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

export default function NotFound() {
  const { t } = useTranslation()

  return (
    <main className="page narrow">
      <h1>{t('notFound.title')}</h1>
      <p className="hint">{t('notFound.hint')}</p>
      <p>
        <Link to="/">{t('notFound.home')}</Link>
      </p>
    </main>
  )
}
