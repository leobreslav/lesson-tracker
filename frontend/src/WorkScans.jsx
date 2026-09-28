import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import ScanWizard from './ScanWizard'
import { fetchWork } from './api'

/**
 * Разбор сканов работы — своей страницей.
 *
 * Окном поверх списка он был, и жаловались на него дважды: вёрстка в окне
 * разваливалась, а сам процесс в окно не помещался по существу. Это не
 * диалог на три поля, а работа на полчаса: тридцать страниц, на каждой надо
 * посмотреть на лист, сличить с прочитанным, назначить хозяина и перейти к
 * следующей. Такой работе нужна страница целиком — прокрутка у страницы, а
 * не у окна внутри экрана; адрес, на который можно вернуться; «назад» в
 * браузере, которое ведёт на работу, а не закрывает всё разом.
 *
 * Адрес — `/works/:id/scans`, рядом с самой работой: сканы это то, что с ней
 * делают, а не отдельный раздел.
 *
 * Страница только рамка. Шаги, чтение и запись живут в `ScanWizard`, и про
 * то, страница вокруг него или окно, он не знает.
 */
export default function WorkScans() {
  const { id } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [work, setWork] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    fetchWork(id)
      .then((answer) => alive && setWork(answer))
      .catch((problem) => alive && setError(problem.message))
    return () => {
      alive = false
    }
  }, [id])

  const back = () => navigate(`/works/${id}`)

  return (
    <main className="page wide scan-page">
      {/* Дорога назад — к работе, из которой пришли: первой строкой и у
          левого края, как у самой страницы работы */}
      <button type="button" className="link screen-back" onClick={back}>
        {work
          ? t('scan.backToWork', { name: work.title })
          : t('scan.backToWorkUnnamed')}
      </button>

      <header className="page-header">
        <h1>{work ? t('scan.title', { name: work.title }) : t('scan.open')}</h1>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!work && !error && <p className="hint">{t('common.loading')}</p>}

      {/* Карточка, как у остальных страниц: без неё шаги мастера стояли бы
          прямо на фоне страницы, и поля с таблицами читались бы чужими */}
      {work && (
        <section className="panel">
          <ScanWizard work={work} onClose={back} />
        </section>
      )}
    </main>
  )
}
