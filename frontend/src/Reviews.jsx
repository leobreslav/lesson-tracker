import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import EmptyState from './EmptyState'
import Modal from './Modal'
import {
  approveReview,
  fetchReview,
  fetchReviews,
  returnReview,
} from './api'
import { longDate } from './dates'

/**
 * «На утверждение» — очередь методиста.
 *
 * Раздел виден только тем, у кого есть назначения по предметам: роль не
 * иерархическая, у большинства список пуст, и пустой раздел в баре был бы
 * обещанием работы, которой нет.
 *
 * Методист читает и решает: утвердить или вернуть с замечанием. Править
 * чужой план он не может — не из вежливости, а чтобы учитель однажды не
 * обнаружил у себя чужие уроки.
 */
export default function Reviews({ onLoggedOut }) {
  const { t } = useTranslation()
  const [reviews, setReviews] = useState(null)
  const [opened, setOpened] = useState(null)
  const [comment, setComment] = useState('')
  const [returning, setReturning] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  const load = useCallback(
    () => fetchReviews().then((result) => setReviews(result.reviews)),
    [],
  )

  useEffect(() => {
    let cancelled = false
    load().catch((err) => !cancelled && handleError(err))
    return () => {
      cancelled = true
    }
  }, [load, handleError])

  const open = async (id) => {
    setError(null)
    try {
      setOpened(await fetchReview(id))
    } catch (err) {
      handleError(err)
    }
  }

  const decide = async (action) => {
    setBusy(true)
    setError(null)

    try {
      await action()
      setOpened(null)
      setReturning(false)
      setComment('')
      await load()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  if (reviews === null) {
    return (
      <main className="page wide">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{t('reviews.title')}</h1>
      </header>

      <p className="hint">{t('reviews.hint')}</p>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!reviews.length ? (
        <EmptyState title={t('reviews.empty.title')}>
          {t('reviews.empty.hint')}
        </EmptyState>
      ) : (
        <ul className="people-list">
          {reviews.map((review) => (
            <li key={review.id}>
              <div className="row">
                <span className="who">{review.teacher.name}</span>
                <span>{review.course.name}</span>
                <span className="hint">{review.course.subject}</span>
                <span className="hint">
                  {t('reviews.sentOn', {
                    date: longDate(review.submitted_at.slice(0, 10)),
                  })}
                </span>
                <span className="hint">
                  {t('common.lessonCount', { count: review.lessons })}
                </span>
                <button type="button" onClick={() => open(review.id)}>
                  {t('reviews.open')}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {opened && (
        <Modal onClose={() => setOpened(null)}>
          <h3>
            {opened.course.name} · {opened.teacher.name}
          </h3>

          <div className="cards">
            <section className="panel card-stat">
              <h2>{opened.lessons}</h2>
              <p className="hint">{t('reviews.lessons')}</p>
            </section>
            <section className="panel card-stat">
              <h2>{opened.slots_total}</h2>
              <p className="hint">{t('reviews.slots')}</p>
            </section>
            <section
              className={`panel card-stat ${opened.reserve < 0 ? 'bad' : 'good'}`}
            >
              <h2>
                {opened.reserve > 0 ? '+' : ''}
                {opened.reserve}
              </h2>
              <p className="hint">{t('reviews.reserve')}</p>
            </section>
          </div>

          {/* план целиком — тот снимок, который прислали, а не то, во что
              он превратился с тех пор */}
          <ul className="review-plan">
            {opened.rows.map((row) => (
              <li
                key={row.position}
                className={row.is_section ? 'section' : 'lesson'}
              >
                {row.title}
              </li>
            ))}
          </ul>

          {returning ? (
            <div className="panel">
              <label className="field-with-hint">
                <span>{t('reviews.comment')}</span>
                <textarea
                  autoFocus
                  rows={3}
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                />
              </label>
              <div className="actions">
                <button
                  type="button"
                  disabled={busy || !comment.trim()}
                  onClick={() => decide(() => returnReview(opened.id, comment.trim()))}
                >
                  {t('reviews.sendBack')}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setReturning(false)}
                >
                  {t('common.cancel')}
                </button>
              </div>
            </div>
          ) : (
            <div className="actions wrap">
              <button
                type="button"
                disabled={busy}
                onClick={() => decide(() => approveReview(opened.id))}
              >
                {t('reviews.approve')}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setReturning(true)}
              >
                {t('reviews.return')}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setOpened(null)}
              >
                {t('common.cancel')}
              </button>
            </div>
          )}
        </Modal>
      )}
    </main>
  )
}
