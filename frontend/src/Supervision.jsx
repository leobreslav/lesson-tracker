import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import CourseRow from './CourseRow'
import { DiffBody } from './PlanDiff'
import Switch from './Switch'
import { shortDate } from './dates'
import { approveReview, fetchReview, fetchReviewDiff, returnReview } from './api'

/**
 * Чужой план глазами методиста — на месте своего.
 *
 * Раздела «Мои курсы» больше нет, и надзор переехал сюда: курс выбирается тем
 * же селектом, только из другой его группы. Числа те же, что видит учитель у
 * себя, и считает их тот же `plans/progress.py` — два ответа на один вопрос
 * означали бы, что разговор про «отстаёшь» начинается со спора о цифрах.
 *
 * План виден **всегда**, а не только по присланному запросу. Границей права
 * это никогда и не было: право читать даёт назначение методистом, а очередь
 * на подпись была просто единственным входом — и потому решала заодно, что
 * методисту видно. Спрашивают же с него ровно про то, чего в очереди нет:
 * кто отстаёт, у кого план не помещается в год, что вообще написано в курсе,
 * который никто не присылал.
 *
 * Поэтому ключ здесь — курс, а не запрос: запрос стал пометкой в строке и
 * подписью над планом («на утверждение не присылали»).
 *
 * Утвердить или вернуть — здесь же, и только когда есть что решать. Возврат
 * без замечания не принимается: учителю нечего исправлять, а «верните как
 * было» — не разговор.
 */
export default function Supervision({ row, busy, onError, onDone }) {
  const { t } = useTranslation()
  const [plan, setPlan] = useState(null)
  // сравнение с эталоном — второй взгляд на тот же присланный план, а не
  // второй экран: спрашивают тут «что изменилось», а не «что написано»
  const [diff, setDiff] = useState(null)
  const [comparing, setComparing] = useState(false)
  // версия эталона: null — последнее утверждение
  const [chosen, setChosen] = useState(null)
  const [returning, setReturning] = useState(false)
  const [comment, setComment] = useState('')

  const request = row.review?.status === 'pending' ? row.review : null

  useEffect(() => {
    setPlan(null)
    setDiff(null)
    setComparing(false)
    setChosen(null)
    setReturning(false)
    setComment('')

    fetchReview(row.id).then(setPlan).catch(onError)
  }, [row.id])

  useEffect(() => {
    // прежнее сравнение остаётся на экране, пока едет новая версия: иначе
    // смена версии на миг возвращала бы к списку плана
    fetchReviewDiff(row.id, chosen).then(setDiff).catch(onError)
  }, [row.id, chosen])

  /**
   * Что сказать про утверждение — ровно то же, что видит учитель.
   *
   * Ветки и фразы взяты у страницы плана (`plan.baseline.*`): один факт
   * должен читаться одинаково на обоих экранах, иначе разговор про план
   * начинается со сверки формулировок.
   */
  const approved = row.baseline
  const waiting = row.review
  const state = (() => {
    if (waiting?.status === 'pending') {
      return {
        kind: 'pending',
        text: t('plan.baseline.pending', { name: waiting.reviewer?.name ?? '' }),
      }
    }
    if (waiting?.status === 'returned') {
      return {
        kind: 'returned',
        text: `${t('plan.baseline.returned', {
          name: waiting.reviewer?.name ?? '',
        })} ${waiting.comment}`,
      }
    }
    if (approved) {
      return {
        kind: 'approved',
        text: t(
          approved.self_approved
            ? 'plan.baseline.approvedSelf'
            : 'plan.baseline.approved',
          {
            date: shortDate(approved.approved_at.slice(0, 10)),
            name: approved.reviewer?.name ?? '',
          },
        ),
      }
    }
    return null
  })()

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

      {/*
        Состояние утверждения — теми же словами, что у автора плана.

        Плашкой оно было («эталон не утверждён», «+3 добавлено в план»), и
        это был второй способ сказать то, что учитель у себя читает строкой
        в шапке, а разбирает — в сравнении. Два вида одного факта
        расходятся молча: плашка считала переименование ничем, сравнение
        считает его правкой, и спорить об этом методист с учителем стали бы
        глядя каждый в свой экран. Поэтому строка тут одна и ключи у неё те
        же, что на странице плана, а «чем разошлось» отвечает тумблер
        «Сравнение» ниже — общий для обоих.

        Порядок веток тот же: запрос в работе важнее прошлой подписи.
      */}
      {state && <p className={`hint approval ${state.kind}`}>{state.text}</p>}

      {!row.review && !row.baseline && (
        <p className="hint">{t('reviews.nothingSent')}</p>
      )}

      {plan && (
        <section className="panel">
          <div className="panel-head spread">
            {/* «Присланный план» и «План курса» — разные вещи, и путать
                их нельзя: во втором случае методист смотрит рабочий
                черновик, за который автор ещё не отвечал */}
            <h3>
              {t(
                comparing
                  ? 'plan.diff.title'
                  : request
                    ? 'reviews.sentPlan'
                    : 'reviews.coursePlan',
              )}
            </h3>
            <span className="row">
              {/* сравнивать не с чем, пока план не утверждали ни разу:
                  первый запрос и есть точка отсчёта. Тумблер тот же, что у
                  автора плана: два вида, оба названы */}
              {diff?.baseline && (
                <Switch
                  label={t('plan.diff.switch')}
                  value={comparing}
                  onChange={setComparing}
                  options={[
                    { value: false, label: t('plan.diff.plan') },
                    { value: true, label: t('plan.diff.toggle') },
                  ]}
                />
              )}
            </span>
          </div>

          {/* план целиком — тот, что методист видит сейчас: правки после
              отправки ничего не отзывают, и утверждается увиденное */}
          {comparing && diff ? (
            <DiffBody data={diff} onVersion={setChosen} />
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

          {/* решают только то, что прислали: у курса без запроса кнопки
              обещали бы действие, которого сервер не сделает */}
          {request &&
            (returning ? (
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
                  onClick={() => decide(() => returnReview(row.id, comment.trim()))}
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
                onClick={() => decide(() => approveReview(row.id))}
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
            ))}
        </section>
      )}
    </>
  )
}
