import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import CourseRow from './CourseRow'
import MathText from './MathText'
import { DiffBody } from './PlanDiff'
import Switch from './Switch'
import { shortDate } from './dates'
import { approveReview, fetchReview, fetchReviewDiff, returnReview } from './api'

/**
 * Чужой план — на месте своего.
 *
 * Экраном методиста это было, и осталось им же: числа те же, что видит
 * учитель у себя, и считает их тот же `plans/progress.py` — два ответа на
 * один вопрос означали бы, что разговор про «отстаёшь» начинается со спора о
 * цифрах.
 *
 * **Читает его теперь вся школа**, а не один назначенный методист. Границей
 * права надзор никогда и не был: чужую программу открывают не только затем,
 * чтобы её подписать, — смежник сверяет, когда у соседей производная,
 * заменяющий смотрит, на чём остановились, новый учитель читает прошлогоднюю
 * параллель. Всем им отвечала библиотека, то есть **снимок**, который кто-то
 * догадался положить на полку; живой план соседа просто ни разу не
 * открывали. Второго экрана под это не завели: он показывал бы ровно то же
 * самое и разошёлся бы с этим в первую же правку.
 *
 * План виден **всегда**, а не только по присланному запросу: запрос — это
 * пометка в строке и подпись над планом («на утверждение не присылали»).
 *
 * Утвердить или вернуть — здесь же, и только у того, кому это можно
 * (`may_decide` с сервера). Возврат без замечания не принимается: учителю
 * нечего исправлять, а «верните как было» — не разговор.
 *
 * **Собирается экран из одного ответа, по одному id курса.** Строка
 * состояния приезжала пропом из списка надзора — то есть экран открывался
 * только тому, у кого этот курс в списке, а у рядового учителя списка нет
 * вовсе, и половина экрана осталась бы пустой.
 */
export default function Supervision({ courseId, busy, onError, onDone }) {
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

  const row = plan?.row ?? null
  const request = row?.review?.status === 'pending' ? row.review : null

  useEffect(() => {
    setPlan(null)
    setDiff(null)
    setComparing(false)
    setChosen(null)
    setReturning(false)
    setComment('')

    fetchReview(courseId).then(setPlan).catch(onError)
  }, [courseId])

  useEffect(() => {
    // прежнее сравнение остаётся на экране, пока едет новая версия: иначе
    // смена версии на миг возвращала бы к списку плана
    fetchReviewDiff(courseId, chosen).then(setDiff).catch(onError)
  }, [courseId, chosen])

  /**
   * Что сказать про утверждение — ровно то же, что видит учитель.
   *
   * Ветки и фразы взяты у страницы плана (`plan.baseline.*`): один факт
   * должен читаться одинаково на обоих экранах, иначе разговор про план
   * начинается со сверки формулировок.
   */
  const approved = row?.baseline
  const waiting = row?.review
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

  /**
   * Решили — и экран показывает решённое, не дожидаясь ничего.
   *
   * Состояние приезжало сюда пропом из списка надзора, и обновлял его
   * `onDone` снаружи, перечитывая список. Теперь экран собирает себя сам, и
   * тот же `onDone` его не касается — после «Утвердить» кнопки оставались
   * на месте, а заголовок по-прежнему говорил «Присланный план».
   *
   * Перечитывать при этом нечего: и утверждение, и возврат отвечают **тем
   * же** полным ответом экрана, что и открытие. Второй запрос следом
   * означал бы состояние между ними — то, за которое отвечать некому.
   */
  const decide = async (action) => {
    try {
      setPlan(await action())
      setReturning(false)
      setComment('')
      onDone()
    } catch (err) {
      onError(err)
    }
  }

  /*
   * Пока ответа нет, экрана нет: рисовать шапку из полупустых полей
   * незачем, а собирается она вся из одного запроса.
   */
  if (!row) return null

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

      {/* «На утверждение не присылали» сказано тому, кто утверждает: для
          него это состояние работы. Читателю со стороны эта строка сообщает
          про процедуру, в которой он не участвует, — то есть ни о чём */}
      {plan.may_decide && !row.review && !row.baseline && (
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
                  {/* формулы рисуются формулами, как в таблице плана и в
                      сравнении: `$\sin(a+b)$` в списке из сорока строк
                      читается хуже, чем сама математика, — и методисту
                      незачем видеть план хуже, чем его видит автор */}
                  <MathText text={item.title} />
                </li>
              ))}
            </ul>
          )}

          {/* Решают только то, что прислали, и только те, кому это можно:
              у курса без запроса кнопки обещали бы действие, которого
              сервер не сделает, а у читателя со стороны — действие, на
              которое он получит отказ. Право приезжает ответом, а не
              выводится из роли: правило сложнее роли — методист **этого
              курса**. */}
          {plan.may_decide &&
            request &&
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
                  onClick={() => decide(() => returnReview(courseId, comment.trim()))}
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
                onClick={() => decide(() => approveReview(courseId))}
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
