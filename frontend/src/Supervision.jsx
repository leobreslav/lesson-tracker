import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import CourseRow from './CourseRow'
import { DiffBody } from './PlanDiff'
import { approveReview, fetchReview, fetchReviewDiff, returnReview } from './api'

/**
 * Чужой план глазами методиста — на месте своего.
 *
 * Раздела «Мои курсы» больше нет, и надзор переехал сюда: курс выбирается тем
 * же селектом, только из другой его группы. Числа те же, что видит учитель у
 * себя, и считает их тот же `plans/progress.py` — два ответа на один вопрос
 * означали бы, что разговор про «отстаёшь» начинается со спора о цифрах.
 *
 * План показывается **только когда его прислали**: читать чужую программу без
 * запроса методист и раньше не мог, и новых прав переезд не даёт. У курса без
 * запроса видно ровно то же, что видно было в списке, — как он идёт.
 *
 * Утвердить или вернуть — здесь же. Возврат без замечания не принимается:
 * учителю нечего исправлять, а «верните как было» — не разговор.
 */
export default function Supervision({ row, busy, onError, onDone }) {
  const { t } = useTranslation()
  const [plan, setPlan] = useState(null)
  // сравнение с эталоном — второй взгляд на тот же присланный план, а не
  // второй экран: спрашивают тут «что изменилось», а не «что написано»
  const [diff, setDiff] = useState(null)
  const [comparing, setComparing] = useState(false)
  const [returning, setReturning] = useState(false)
  const [comment, setComment] = useState('')

  const request = row.review?.status === 'pending' ? row.review : null

  useEffect(() => {
    setPlan(null)
    setDiff(null)
    setComparing(false)
    setReturning(false)
    setComment('')
    if (!request) return

    fetchReview(request.id).then(setPlan).catch(onError)
    fetchReviewDiff(request.id).then(setDiff).catch(onError)
  }, [request?.id])

  const decide = async (action) => {
    try {
      await action()
      onDone()
    } catch (err) {
      onError(err)
    }
  }

  return (
    <>
      <ul className="progress-list">
        <CourseRow
          row={row}
          open
          onToggle={() => {}}
          mark={
            /* одной ячейкой: в шапке сетка на четыре колонки, и две
               отдельные пометки разъехались бы по разным местам */
            <span className="whose">
              {/* курс без ведущего — нормальное состояние: нагрузку ещё не
                  раздали, и методисту это как раз видно */}
              {row.teacher?.name ?? t('reviews.noTeacher')}
              {request && <span className="badge waiting">{t('reviews.mark')}</span>}
            </span>
          }
        />
      </ul>

      {!request && <p className="hint">{t('reviews.nothingSent')}</p>}

      {plan && (
        <section className="panel">
          <div className="panel-head spread">
            <h3>{t(comparing ? 'plan.diff.title' : 'reviews.sentPlan')}</h3>
            <span className="row">
              {/* сравнивать не с чем, пока план не утверждали ни разу:
                  первый запрос и есть точка отсчёта */}
              {diff?.baseline && (
                <button
                  type="button"
                  className="secondary compact"
                  onClick={() => setComparing(!comparing)}
                >
                  {t(comparing ? 'plan.diff.wholePlan' : 'plan.diff.toggle')}
                </button>
              )}
              <span className="hint">
                {t('reviews.reserve')}: {plan.reserve > 0 ? '+' : ''}
                {plan.reserve}
              </span>
            </span>
          </div>

          {/* план целиком — тот, что методист видит сейчас: правки после
              отправки ничего не отзывают, и утверждается увиденное */}
          {comparing && diff ? (
            <DiffBody data={diff} />
          ) : (
            <ul className="review-plan">
              {plan.rows.map((item) => (
                <li
                  key={item.position}
                  className={item.is_section ? 'section' : 'lesson'}
                >
                  {item.title}
                </li>
              ))}
            </ul>
          )}

          {returning ? (
            <>
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
                  onClick={() => decide(() => returnReview(plan.id, comment.trim()))}
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
            </>
          ) : (
            <div className="actions wrap">
              <button
                type="button"
                disabled={busy}
                onClick={() => decide(() => approveReview(plan.id))}
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
            </div>
          )}
        </section>
      )}
    </>
  )
}
