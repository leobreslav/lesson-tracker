import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import CourseRow from './CourseRow'
import Modal from './Modal'
import { approveReview, fetchReview, fetchReviews, returnReview } from './api'
import { longDate } from './dates'

/**
 * Надзор методиста — блок на главной, под своими курсами.
 *
 * Своим разделом это было, и раздел оказался лишним: методист заходит на
 * главную посмотреть, как идут **его** курсы, и там же должен видеть, что
 * ждёт его ответа. Отдельный адрес заставлял вспоминать, что он вообще
 * существует, а счётчик в баре — единственное, что об этом напоминало.
 *
 * Внутри блока два списка. Сверху то, что ждёт ответа: за этим сюда и
 * приходят. Ниже — остальные планы под надзором, и они нужны не меньше:
 * очередь отвечала на вопрос «что подписать», а спрашивают с методиста про
 * тех, кто ничего не присылал — кто отстаёт, у кого план не помещается в
 * год, кто переписал половину после утверждения.
 *
 * Строки те же, что у своих курсов выше (`CourseRow`), и числа в них
 * считает тот же серверный расчёт: методист и учитель должны смотреть на
 * одно и то же, иначе разговор про «отстаёшь» начинается со спора о
 * цифрах. Отличий два — в шапке стоит имя учителя, а под подробностями
 * появляется кнопка разбора, если план ждёт ответа.
 *
 * Читать и решать: утвердить или вернуть с замечанием. Править чужой план
 * методист не может — не из вежливости, а чтобы учитель однажды не
 * обнаружил у себя чужие уроки.
 */
export default function Reviews({ onLoggedOut }) {
  const { t } = useTranslation()
  const [plans, setPlans] = useState(null)
  const [opened, setOpened] = useState(null)
  const [expanded, setExpanded] = useState(null)
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

  /** Строку опознаёт пара: курс общий, планов в нём столько же, сколько людей. */
  const key = (plan) => (plan ? `${plan.teacher.id}:${plan.id}` : null)

  const load = useCallback(
    () =>
      fetchReviews().then((result) => {
        setPlans(result.plans)
        // разворачиваем то, что ждёт ответа: за этим сюда и заходят. Ждать
        // нечему — разворачиваем проблемный план, а если и таких нет,
        // список остаётся свёрнутым
        const waiting = result.plans.find(
          (plan) => plan.review?.status === 'pending',
        )
        const trouble = result.plans.find((plan) => plan.reserve < 0)
        setExpanded((current) => current ?? key(waiting ?? trouble))
      }),
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

  // ничего не надзираем — блока нет вовсе: пустой раздел на главной был бы
  // обещанием работы, которой нет
  if (plans === null || !plans.length) return null

  const waiting = plans.filter((plan) => plan.review?.status === 'pending')
  const rest = plans.filter((plan) => plan.review?.status !== 'pending')

  const list = (rows) => (
    <ul className="progress-list">
      {rows.map((plan) => (
        <CourseRow
          key={key(plan)}
          row={plan}
          open={expanded === key(plan)}
          onToggle={() => setExpanded(expanded === key(plan) ? null : key(plan))}
          mark={
            /* одной ячейкой: в шапке сетка на четыре колонки, и две
               отдельные пометки разъехались бы по разным местам */
            <span className="whose">
              {plan.teacher.name}
              {plan.review?.status === 'pending' && (
                <span className="badge waiting">{t('reviews.mark')}</span>
              )}
              {plan.review?.status === 'returned' && (
                <span className="badge">{t('reviews.returned')}</span>
              )}
            </span>
          }
          actions={
            plan.review?.status === 'pending' ? (
              <div className="actions wrap">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => open(plan.review.id)}
                >
                  {t('reviews.open')}
                </button>
                <span className="hint">
                  {t('reviews.sentOn', {
                    date: longDate(plan.review.submitted_at.slice(0, 10)),
                  })}
                </span>
              </div>
            ) : null
          }
        />
      ))}
    </ul>
  )

  return (
    <>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {waiting.length > 0 && (
        <>
          <h2 className="section-title">{t('reviews.title')}</h2>
          <p className="hint">{t('reviews.waiting', { count: waiting.length })}</p>
          {list(waiting)}
        </>
      )}

      {rest.length > 0 && (
        <>
          <h2 className="section-title">{t('reviews.rest')}</h2>
          <p className="hint">{t('reviews.hint')}</p>
          {list(rest)}
        </>
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
    </>
  )
}
