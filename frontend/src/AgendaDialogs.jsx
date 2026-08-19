import { useEffect, useLayoutEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import Modal from './Modal'
import { useDismissable } from './UserMenu'
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
 * Меню у курсора: список действий там, где нажали.
 *
 * Окном это было — тем же `Modal`, что у форм, — и по правой кнопке
 * посреди экрана всплывал модальный диалог с затемнением. Контекстное меню
 * так себя не ведёт: оно появляется у клетки, по которой щёлкнули, и
 * закрывается, стоит нажать мимо.
 *
 * Форма остаётся окном, и это не непоследовательность: список действий и
 * ввод причины переноса — разные вещи. Меню выбирают, а в форме печатают,
 * и печатать в списке, который закрывается кликом мимо, было бы больно.
 *
 * Положение считается после отрисовки: у края экрана меню сдвигается
 * внутрь, а не уезжает за него. До замера оно спрятано `visibility` —
 * иначе первый кадр показывал бы его не на месте.
 */
export function ContextMenu({ at, onClose, children }) {
  const [box, setBox] = useState(null)
  const ref = useDismissable(true, onClose)

  /*
   * Замер — после **каждой** отрисовки, а не один раз при открытии.
   *
   * Меню растёт по дороге: тема урока приезжает отдельным запросом и
   * добавляет строку. Померенное один раз, оно уползало за нижний край —
   * и нижние пункты становились недостижимы. Поймано тестом: «элемент вне
   * области просмотра».
   *
   * Зацикливания нет: то же положение не пишется в состояние.
   */
  useLayoutEffect(() => {
    const menu = ref.current?.getBoundingClientRect()
    if (!menu) return

    const next = {
      top: Math.max(8, Math.min(at.y, window.innerHeight - menu.height - 8)),
      left: Math.max(8, Math.min(at.x, window.innerWidth - menu.width - 8)),
    }
    setBox((current) =>
      current && current.top === next.top && current.left === next.left
        ? current
        : next,
    )
  })

  return (
    <ul
      ref={ref}
      className="dropdown context-menu"
      style={{
        top: box ? box.top : at.y,
        left: box ? box.left : at.x,
        visibility: box ? 'visible' : 'hidden',
      }}
    >
      {children}
    </ul>
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
  at,
  busy,
  onCancel,
  onRestore,
  onDelete,
  onDeleteRow,
  onMove,
  onClose,
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [reason, setReason] = useState('')
  const [mode, setMode] = useState(null) // null | 'cancel' | 'move' | 'row'
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

  /*
   * Всё в одном меню: и список действий, и форма, которую действие
   * открывает.
   *
   * Окном форма была — то есть на один разговор приходилось два вида
   * поверхностей: меню у курсора и модальный диалог поверх него. Причина
   * отмены это две строки ввода, а не отдельный экран, и место у них там
   * же, где нажали.
   *
   * Меню при этом остаётся меню: Escape и клик мимо закрывают его целиком,
   * а «Не надо» возвращает к списку.
   */
  if (mode === null) {
    const item = (key, label, onClick, extra = {}) => (
      <li key={key}>
        <button type="button" disabled={busy} onClick={onClick} {...extra}>
          {label}
        </button>
      </li>
    )

    return (
      <ContextMenu at={at} onClose={onClose}>
        <li className="context-head">
          <span className="hint">
            {lesson.course_name} · {weekdayWithDate(date)}
          </span>
          {/* какая строка плана стоит в этом часе: по ней и ведёт пункт
              «Открыть в учебном плане» */}
          {row && (
            <span className="hint menu-topic">
              {row.section_title ? `${row.section_title} · ` : ''}
              {row.title}
            </span>
          )}
          {/* «дополнительный» — свойство самого часа, и в шапке меню ему
              место рядом с курсом и датой */}
          {lesson.is_extra && <span className="hint">{t('agenda.menu.extra')}</span>}
          {lesson.is_cancelled && (
            <span className="hint">
              {t('agenda.menu.cancelled', {
                reason: lesson.reason ? `: ${lesson.reason}` : '',
              })}
            </span>
          )}
          {!lesson.is_cancelled && lesson.reason && (
            <span className="hint">{lesson.reason}</span>
          )}
        </li>

        {item('open', t('today.openLesson'), () => navigate(`/lesson/${lesson.id}`))}
        {row &&
          item('plan', t('agenda.menu.openPlan'), () =>
            navigate(`/plan?course=${lesson.course_id}&row=${row.plan_row_id}`),
          )}

        <li className="dropdown-sep" />

        {lesson.is_cancelled
          ? item('restore', t('agenda.menu.restore'), onRestore)
          : [
              /* За записанным часом стоит урок: и отмена, и удаление стирают
                 запись, а сервер их отклоняет. Пункт, умеющий только
                 отказать, честнее не рисоваться */
              !lesson.recorded &&
                item('cancel', t('agenda.menu.cancel'), () => setMode('cancel')),
              item('move', t('agenda.menu.move'), () => setMode('move')),
            ].filter(Boolean)}

        {!lesson.recorded && item('delete', t('common.delete'), onDelete)}
        {/* час с записью ряд переживёт: массовая операция его пропустит и
            скажет, сколько уцелело, — поэтому пункт тут всегда */}
        {item('row', t('agenda.menu.deleteRow'), () => setMode('row'))}
      </ContextMenu>
    )
  }

  return (
    <ContextMenu at={at} onClose={onClose}>
      <li className="context-head">
        {/* чей это час и какой: то же, что стояло заголовком окна */}
        <span className="hint">
          {t('agenda.menu.title', {
            className: lesson.course_name,
            number: lesson.lesson_number,
          })}
        </span>
        <span className="hint">{weekdayWithDate(date)}</span>
      </li>

      <li className="context-form">
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

        {mode === 'row' && (
          <>
            <p className="hint">{t('agenda.menu.rowHint')}</p>
            <div className="actions">
              <button type="button" disabled={busy} onClick={onDeleteRow}>
                {t('agenda.menu.rowSubmit')}
              </button>
              <button type="button" className="secondary" onClick={() => setMode(null)}>
                {t('agenda.menu.cancelAbort')}
              </button>
            </div>
          </>
        )}
      </li>
    </ContextMenu>
  )
}
