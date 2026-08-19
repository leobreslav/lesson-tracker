import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import Modal from './Modal'
import { fetchLayoutAgenda } from './api'
import { weekdayWithDate } from './dates'

/**
 * Повтор нового урока: не повторять, каждую неделю или через неделю.
 *
 * Граница спрашивается, а не подразумевается — конец года подставлен, но
 * четверть, полугодие и «до Нового года» встречаются не реже. Считает ряд
 * сервер: сколько дат попадёт под каникулы и сколько мест занято, знает
 * только он, а обещать число, которое потом разойдётся, хуже, чем не
 * обещать ничего.
 */
export function RepeatChoice({ step, until, date, yearEnd, busy, onStep, onUntil }) {
  const { t } = useTranslation()

  return (
    <>
      <div className="row">
        <span className="hint">{t('agenda.add.repeat')}</span>
        {[
          [0, 'agenda.add.repeatNo'],
          [1, 'agenda.add.repeatWeekly'],
          [2, 'agenda.add.repeatBiweekly'],
        ].map(([value, key]) => (
          <label className="checkbox" key={value}>
            <input
              type="radio"
              name="repeat"
              checked={step === value}
              disabled={busy}
              onChange={() => onStep(value)}
            />
            {t(key)}
          </label>
        ))}
      </div>

      {step > 0 && (
        <label className="field-with-hint">
          <span>{t('agenda.add.repeatUntil')}</span>
          <input
            type="date"
            value={until}
            min={date}
            max={yearEnd}
            disabled={busy}
            onChange={(event) => onUntil(event.target.value)}
          />
        </label>
      )}
    </>
  )
}

/** A new lesson in a free window. */
export function AddLessonDialog({
  date,
  number,
  classes,
  yearEnd,
  busy,
  onSubmit,
  onClose,
}) {
  const { t } = useTranslation()
  const [classId, setClassId] = useState(classes[0]?.id ?? null)
  const [isExtra, setIsExtra] = useState(false)
  const [reason, setReason] = useState('')
  // 0 — не повторять, 1 — каждую неделю, 2 — через неделю
  const [step, setStep] = useState(0)
  const [until, setUntil] = useState(yearEnd ?? '')

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!classId) return

    onSubmit({
      course: classId,
      is_extra: isExtra,
      reason: isExtra ? reason.trim() : '',
      // повтор — свойство ряда, а не клетки: у дополнительного урока его
      // не бывает по смыслу, он разовый
      ...(step && !isExtra ? { step, until } : {}),
    })
  }

  return (
    <Modal onClose={onClose} title={t('agenda.add.title', { date: weekdayWithDate(date), number })}>
      <form onSubmit={handleSubmit}>

        {!classes.length ? (
          <p className="hint">{t('agenda.add.nobody')}</p>
        ) : (
          <>
            <label>
              {t('agenda.add.classLabel')}
              <select
                autoFocus
                value={classId ?? ''}
                disabled={busy}
                onChange={(event) => setClassId(Number(event.target.value))}
              >
                {classes.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="checkbox">
              <input
                type="checkbox"
                checked={isExtra}
                disabled={busy}
                onChange={(event) => setIsExtra(event.target.checked)}
              />
              {t('agenda.add.extra')}
            </label>

            {isExtra && (
              <input
                value={reason}
                maxLength={200}
                placeholder={t('agenda.add.reasonPlaceholder')}
                aria-label={t('agenda.add.reasonLabel')}
                disabled={busy}
                onChange={(event) => setReason(event.target.value)}
              />
            )}

            {/*
              Повтор прямо здесь, а не «нарисуй клетку, потом копируй
              неделю»: сетку строят рядами — «вторник, третий час, до конца
              года», — и ради одного часа раскатывать всю неделю значило
              задевать всё, что в ней уже стоит.

              Дополнительному уроку повтора не предлагаем: он разовый по
              определению — замена, отработка, кружок.
            */}
            {!isExtra && <RepeatChoice
              step={step}
              until={until}
              date={date}
              yearEnd={yearEnd}
              busy={busy}
              onStep={setStep}
              onUntil={setUntil}
            />}
          </>
        )}

        <div className="actions">
          <button type="submit" disabled={busy || !classes.length}>
            {t('common.add')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/**
 * What can be done with a lesson that is already there.
 *
 * Перенос стоит здесь же, рядом с отменой, и это не случайно: для человека
 * это одно действие, а в данных — отмена с причиной плюс дополнительное
 * занятие на новой дате. Двойную запись делает сервер; здесь только форма.
 *
 * **Первым стоит «Открыть урок»**, и это же единственная синяя кнопка. Меню
 * отвечало только на вопрос «что сделать с клеткой расписания» — отменить,
 * перенести, удалить, — и попасть из расписания в само занятие было нечем:
 * приходилось идти через экран дня и долистывать до нужного. А работают
 * с занятием чаще, чем правят сетку.
 *
 * Синей до этого была «Отменить», по единственной причине — она стояла
 * первой. Отмена редка и разрушительна, и главной кнопкой быть не должна:
 * то же решение, что увело её в «⋯» на самой странице урока.
 */
export function LessonMenu({
  lesson,
  date,
  busy,
  onCancel,
  onRestore,
  onDelete,
  onMove,
  onClose,
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [reason, setReason] = useState('')
  const [mode, setMode] = useState(null) // null | 'cancel' | 'move'
  const [target, setTarget] = useState({ date: '', number: lesson.lesson_number })
  // строка плана, попавшая в этот час: {plan_row_id, title, section_title}
  const [row, setRow] = useState(null)

  /*
   * Какая строка плана стоит в этом часе — спрашивается при открытии меню.
   *
   * Сводное расписание тянет темы на весь период, но только при включённом
   * чекбоксе: иначе каждая неделя стоила бы лишнего запроса. Меню открывают
   * редко и по одному часу, поэтому здесь запрос свой и ровно на один день.
   *
   * Ответа может не быть вовсе — у отменённого часа строки нет по
   * построению, а у лишнего часа её не хватило, — и тогда вести некуда.
   */
  useEffect(() => {
    let cancelled = false

    fetchLayoutAgenda(date, date)
      .then((payload) => {
        if (!cancelled) setRow(payload.slots?.[lesson.id] ?? null)
      })
      // молча: переход в план — удобство, и меню из-за него ломаться не должно
      .catch(() => {})

    return () => {
      cancelled = true
    }
  }, [date, lesson.id])

  const handleCancel = (event) => {
    event.preventDefault()
    onCancel(reason.trim())
  }

  const handleMove = (event) => {
    event.preventDefault()
    if (!target.date) return

    onMove({
      date: target.date,
      lesson_number: Number(target.number),
      // причина пишется на языке того, кто нажал: это контент в базе, и
      // сервер его не сочиняет
      reason: reason.trim() || t('agenda.menu.movedReason', { date: target.date }),
    })
  }

  return (
    <Modal
      onClose={onClose}
      title={t('agenda.menu.title', {
        className: lesson.course_name,
        number: lesson.lesson_number,
      })}
    >
      <p className="hint">{weekdayWithDate(date)}</p>

      {lesson.is_extra && <p className="hint">{t('agenda.menu.extra')}</p>}
      {lesson.is_cancelled && (
        <p className="hint">
          {t('agenda.menu.cancelled', {
            reason: lesson.reason ? `: ${lesson.reason}` : '',
          })}
        </p>
      )}
      {!lesson.is_cancelled && lesson.reason && (
        <p className="hint">{lesson.reason}</p>
      )}

      {mode === 'cancel' && (
        <form onSubmit={handleCancel}>
          <input
            autoFocus
            value={reason}
            maxLength={200}
            placeholder={t('agenda.menu.cancelReason')}
            aria-label={t('agenda.menu.cancelReason')}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="actions">
            <button type="submit" disabled={busy}>
              {t('agenda.menu.cancelSubmit')}
            </button>
            <button type="button" className="secondary" onClick={() => setMode(null)}>
              {t('agenda.menu.cancelAbort')}
            </button>
          </div>
        </form>
      )}

      {mode === 'move' && (
        <form onSubmit={handleMove}>
          <p className="hint">{t('agenda.menu.moveHint')}</p>
          <div className="row">
            <input
              autoFocus
              type="date"
              value={target.date}
              aria-label={t('agenda.menu.moveDate')}
              onChange={(event) =>
                setTarget((current) => ({ ...current, date: event.target.value }))
              }
            />
            <input
              type="number"
              min={1}
              max={10}
              value={target.number}
              aria-label={t('agenda.menu.moveNumber')}
              onChange={(event) =>
                setTarget((current) => ({ ...current, number: event.target.value }))
              }
            />
          </div>
          <input
            value={reason}
            maxLength={200}
            placeholder={t('agenda.menu.moveReason')}
            aria-label={t('agenda.menu.moveReason')}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="actions">
            <button type="submit" disabled={busy || !target.date}>
              {t('agenda.menu.moveSubmit')}
            </button>
            <button type="button" className="secondary" onClick={() => setMode(null)}>
              {t('agenda.menu.cancelAbort')}
            </button>
          </div>
        </form>
      )}

      {/* какая строка плана стоит в этом часе: по ней и ведёт кнопка ниже */}
      {mode === null && row && (
        <p className="hint menu-topic">
          {row.section_title ? `${row.section_title} · ` : ''}
          {row.title}
        </p>
      )}

      {mode === null && (
        <div className="actions">
          <button type="button" onClick={() => navigate(`/lesson/${lesson.id}`)}>
            {t('today.openLesson')}
          </button>
          {/* Второй путь из клетки — в программу: «что мы вообще проходим и
              где мы в ней сейчас». Из занятия он есть давно, а из сетки
              приходилось идти через занятие. Ведёт на **эту** строку: на
              сотне уроков искать её глазами — минута */}
          {row && (
            <button
              type="button"
              className="secondary"
              onClick={() =>
                navigate(
                  `/plan?course=${lesson.course_id}&row=${row.plan_row_id}`,
                )
              }
            >
              {t('agenda.menu.openPlan')}
            </button>
          )}
          {lesson.is_cancelled ? (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={onRestore}
            >
              {t('agenda.menu.restore')}
            </button>
          ) : (
            <>
              {/* За записанным часом стоит урок: и отмена, и удаление
                  стирают запись, а сервер их отклоняет. Кнопка, которая
                  умеет только отказать, честнее не рисоваться — снимают
                  запись на самой странице занятия, оттуда и продолжают */}
              {!lesson.recorded && (
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => setMode('cancel')}
                >
                  {t('agenda.menu.cancel')}
                </button>
              )}
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setMode('move')}
              >
                {t('agenda.menu.move')}
              </button>
            </>
          )}
          {!lesson.recorded && (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={onDelete}
            >
              {t('common.delete')}
            </button>
          )}
        </div>
      )}
    </Modal>
  )
}
