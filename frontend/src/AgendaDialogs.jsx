import { useEffect, useLayoutEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import Modal from './Modal'
import Switch from './Switch'
import { useDismissable } from './UserMenu'
import { fetchLayoutAgenda } from './api'
import { weekdayWithDate } from './dates'
import { addDays, startOfWeek } from './calendarLogic'

/** Разовый перенос: отмена здесь, дополнительное занятие там. */
export const MOVE_ONCE = 'once'
/** Постоянная правка расписания: ряд переезжает, отмен и лишних часов нет. */
export const MOVE_SERIES = 'series'

/**
 * Бывает ли у этого часа ряд, которым он может переехать.
 *
 * Отменённый и дополнительный разовые по определению, а за записанным
 * стоит прошедший урок — он привязан к дню, в который случился. Сервер
 * отказывает всем троим, и предлагать им выбор незачем: пункт, умеющий
 * только отказать, честнее не рисоваться.
 */
export function movesAsRow(lesson) {
  return !lesson.recorded && !lesson.is_extra && !lesson.is_cancelled
}

/**
 * Тело запроса на перенос: у двух режимов оно разное.
 *
 * Причина уезжает в базу текстом отмены на старом месте и пишется на языке
 * нажавшего — сервер контент не сочиняет, поэтому `t` приезжает сюда
 * аргументом. У постоянной правки отменять нечего, и причины у неё нет
 * вовсе.
 *
 * Живёт это здесь, а не в двух страницах сразу: обе сетки — учительская и
 * школьная — зовут один и тот же перенос, и две копии одного тела
 * разошлись бы молча, начиная с формулировки причины.
 */
export function moveBody(target, mode, t) {
  if (mode === MOVE_SERIES) return { ...target, mode: MOVE_SERIES }

  return {
    ...target,
    mode: MOVE_ONCE,
    reason: t('agenda.menu.movedReason', { date: target.date }),
  }
}

/**
 * Чем этот перенос будет: срывом одного часа или новым расписанием.
 *
 * Вопрос один, а событий за ним два, и различает их не механика, а то, что
 * произошло. Сорвался час — старое место остаётся отменённым, на новом
 * появляется дополнительное занятие, и администрация видит срыв и
 * компенсацию. Изменилось расписание — ряд просто переехал, и объявлять
 * тридцать срывов, которых не было, было бы враньём в тех самых числах,
 * которые она и читает.
 *
 * Поэтому подсказка меняется вместе с выбором: два предложения тут дороже
 * самого тумблера — по названиям сегментов разница не читается.
 */
export function MoveModeChoice({ value, busy, onChange }) {
  const { t } = useTranslation()

  return (
    <>
      <Switch
        label={t('agenda.menu.moveMode')}
        value={value}
        disabled={busy}
        onChange={onChange}
        options={[
          { value: MOVE_ONCE, label: t('agenda.menu.moveOnce') },
          { value: MOVE_SERIES, label: t('agenda.menu.moveSeries') },
        ]}
      />
      <p className="hint">
        {t(
          value === MOVE_SERIES
            ? 'agenda.menu.moveSeriesHint'
            : 'agenda.menu.moveHint',
        )}
      </p>
    </>
  )
}

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
/**
 * Выбор кабинета: один блок на все формы, где час заводят или правят.
 *
 * Пусто — законное состояние и означает «не указан», а не «неизвестно
 * откуда взять»: школа, не ведущая кабинеты, живёт как жила. Поэтому
 * первым пунктом стоит именно пустой, а не первый кабинет по алфавиту:
 * подставленный сам собой кабинет — это тихо сказанная неправда о том, где
 * идёт урок.
 *
 * Архивные не показываются: кабинет убрали из выбора ровно затем, чтобы в
 * него больше не ставили. Уже проставленный остаётся — в списке он
 * появляется, пока стоит у этого часа, иначе правка соседнего поля молча
 * стирала бы кабинет.
 */
export function RoomChoice({ rooms, value, busy, onChange }) {
  const { t } = useTranslation()

  const shown = rooms.filter((room) => !room.is_archived || room.id === value)
  if (!rooms.length) return null

  return (
    <label>
      {t('agenda.add.roomLabel')}
      <select
        value={value ?? ''}
        disabled={busy}
        onChange={(event) =>
          onChange(event.target.value ? Number(event.target.value) : null)
        }
      >
        <option value="">{t('agenda.add.noRoom')}</option>
        {shown.map((room) => (
          <option key={room.id} value={room.id}>
            {room.name}
          </option>
        ))}
      </select>
    </label>
  )
}

export function AddLessonDialog({
  date,
  number,
  classes,
  rooms = [],
  yearEnd,
  busy,
  onSubmit,
  onClose,
}) {
  const { t } = useTranslation()
  const [classId, setClassId] = useState(classes[0]?.id ?? null)
  const [room, setRoom] = useState(null)
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
      room,
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

            <RoomChoice rooms={rooms} value={room} busy={busy} onChange={setRoom} />

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
 * Что за перенос сейчас произошёл — спрашивается там, где отпустили.
 *
 * Жест заведён ради скорости, и лишний вопрос ему дорог. Но ответов на
 * него два, и молчаливое умолчание тут стоит дороже: разовый перенос
 * оставляет отмену и дополнительный час, и человек, менявший расписание
 * насовсем, узнаёт об этом к маю — по двенадцати срывам, которых не было.
 *
 * Поэтому вопрос ставится один и одним нажатием: два пункта у самого
 * курсора, Escape и клик мимо отменяют перенос целиком. У часа, которому
 * ряд не полагается (записанный, дополнительный), выбора нет вовсе — там
 * жест работает как работал, без остановки.
 */
export function MoveModeMenu({ at, target, busy, onPick, onClose }) {
  const { t } = useTranslation()

  return (
    <ContextMenu at={at} onClose={onClose}>
      <li className="context-head">
        <span className="hint">
          {t('agenda.menu.moveTo', {
            date: weekdayWithDate(target.date),
            number: target.lesson_number,
          })}
        </span>
      </li>

      {[
        [MOVE_ONCE, 'agenda.menu.moveOnce', 'agenda.menu.moveHint'],
        [MOVE_SERIES, 'agenda.menu.moveSeries', 'agenda.menu.moveSeriesHint'],
      ].map(([mode, label, hint]) => (
        <li key={mode}>
          <button
            type="button"
            className="menu-choice"
            disabled={busy}
            onClick={() => onPick(mode)}
          >
            {t(label)}
            <span className="hint">{t(hint)}</span>
          </button>
        </li>
      ))}
    </ContextMenu>
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
  rooms = [],
  onCancel,
  onRestore,
  onDelete,
  onDeleteRow,
  onMove,
  onRegular = null,
  onRoom = null,
  onClose,
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [reason, setReason] = useState('')
  const [mode, setMode] = useState(null) // null | 'cancel' | 'move' | 'row' | 'room'
  const [room, setRoom] = useState(lesson.room ?? null)
  const [target, setTarget] = useState({ date: '', number: lesson.lesson_number })
  // «этот час» или «и дальше по расписанию» — см. MoveModeChoice ниже
  const [moveMode, setMoveMode] = useState(MOVE_ONCE)
  // тот же вопрос у кабинета, и по той же причине: расписание строят рядами,
  // и «алгебра по вторникам третьим часом идёт в 214» — одно решение, а не
  // тридцать четыре. Своё состояние, а не общее с переносом: два разговора
  // идут по очереди, и ответ на один не должен подставляться во второй
  const [roomScope, setRoomScope] = useState(MOVE_ONCE)
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

  const handleRoom = (event) => {
    event.preventDefault()
    onRoom(room, roomScope)
  }

  /**
   * Смена режима заодно чистит дату, которая ему не годится.
   *
   * Границы у поля стоят, но набранное **до** переключения они не
   * отменяют: у календаря появились бы серые дни, а в поле осталось бы
   * число из другой недели — и отказ прилетел бы после нажатия, вместо
   * ответа на месте.
   */
  const pickMoveMode = (next) => {
    setMoveMode(next)

    const week = startOfWeek(date)
    if (
      next === MOVE_SERIES &&
      target.date &&
      (target.date < week || target.date > addDays(week, 6))
    ) {
      setTarget((current) => ({ ...current, date: '' }))
    }
  }

  const handleMove = (event) => {
    event.preventDefault()
    if (!target.date) return

    onMove(
      moveMode === MOVE_SERIES
        ? // у постоянной правки причины нет вовсе: отменять нечего, и поле,
          // которое некуда записать, обещало бы след, которого не будет
          {
            date: target.date,
            lesson_number: Number(target.number),
            mode: MOVE_SERIES,
          }
        : {
            date: target.date,
            lesson_number: Number(target.number),
            mode: MOVE_ONCE,
            // причина пишется на языке того, кто нажал: это контент в базе, и
            // сервер его не сочиняет
            reason:
              reason.trim() || t('agenda.menu.movedReason', { date: target.date }),
          },
    )
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
          {/* шапка одна на оба состояния меню — список и форму: курс с
              номером, а под ним день */}
          <span className="hint">
            {t('agenda.menu.title', {
              className: lesson.course_name,
              number: lesson.lesson_number,
            })}
          </span>
          <span className="hint">{weekdayWithDate(date)}</span>
          {/* какая строка плана стоит в этом часе: по ней и ведёт пункт
              «Открыть в учебном плане» */}
          {row && (
            <span className="hint menu-topic">
              {row.section_title ? `${row.section_title} · ` : ''}
              {row.title}
            </span>
          )}
          {/* где идёт — в шапке, а не в списке действий: это не то, что
              с часом делают, а то, что о нём известно */}
          {lesson.room_name && (
            <span className="hint">
              {t('agenda.menu.roomIs', { name: lesson.room_name })}
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
              /*
               * «Дополнительный» снимается там же, где ставится всё
               * остальное про этот час.
               *
               * Поставить флаг можно было только при создании, а снять —
               * ничем: в шапке меню стояла подпись «Дополнительный урок.», и
               * это было единственное свойство часа, которое видно, но не
               * правится. Вернуть такой час в обычную сетку значило удалить
               * его и завести заново — то есть потерять всё, что на нём
               * накопилось.
               *
               * Пункта нет у отменённого часа, и это не забывчивость:
               * причина у него принадлежит отмене (см. `onRegular`), и путь
               * назад там в два шага — сперва «Вернуть», потом уже сюда.
               */
              lesson.is_extra &&
                onRegular &&
                item('regular', t('agenda.menu.makeRegular'), onRegular),
            ].filter(Boolean)}

        {/* кабинет правится там же, где отмена и перенос: это свойство
            того же часа, и ходить за ним на страницу занятия незачем.
            Пункта нет вовсе, пока школа не завела ни одного кабинета —
            выбор из пустого списка обещал бы то, чего нет */}
        {onRoom &&
          rooms.length > 0 &&
          item('room', t('agenda.menu.room'), () => setMode('room'))}

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
            {/* отмена и удаление стоят в меню рядом и по названию
                неразличимы: «Отменить» одинаково читается и как «убрать
                отсюда». Сказано прямо, как у переноса и ряда ниже */}
            <p className="hint">{t('agenda.menu.cancelHint')}</p>
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
            {movesAsRow(lesson) ? (
              <MoveModeChoice value={moveMode} busy={busy} onChange={pickMoveMode} />
            ) : (
              <p className="hint">{t('agenda.menu.moveHint')}</p>
            )}
            <div className="row">
              <input
                autoFocus
                type="date"
                value={target.date}
                /* Постоянная правка — это смена дня недели, а не сдвиг года
                   на девять дней вперёд, и сервер цель из чужой недели не
                   принимает. Границы у поля стоят затем, чтобы отказ не
                   понадобился вовсе: календарь просто не даст выбрать. */
                min={moveMode === MOVE_SERIES ? startOfWeek(date) : undefined}
                max={
                  moveMode === MOVE_SERIES ? addDays(startOfWeek(date), 6) : undefined
                }
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
            {/* причину спрашивает только разовый перенос: у постоянной
                правки отменять нечего, и записать её было бы некуда */}
            {moveMode === MOVE_ONCE && (
              <input
                value={reason}
                maxLength={200}
                placeholder={t('agenda.menu.moveReason')}
                aria-label={t('agenda.menu.moveReason')}
                onChange={(event) => setReason(event.target.value)}
              />
            )}
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

        {mode === 'room' && (
          <form onSubmit={handleRoom}>
            <p className="hint">{t('agenda.menu.roomHint')}</p>
            <RoomChoice rooms={rooms} value={room} busy={busy} onChange={setRoom} />
            <Switch
              label={t('agenda.menu.roomScope')}
              value={roomScope}
              disabled={busy}
              onChange={setRoomScope}
              options={[
                { value: MOVE_ONCE, label: t('agenda.menu.roomOnce') },
                { value: MOVE_SERIES, label: t('agenda.menu.roomSeries') },
              ]}
            />
            <p className="hint">
              {t(
                roomScope === MOVE_SERIES
                  ? 'agenda.menu.roomSeriesHint'
                  : 'agenda.menu.roomOnceHint',
              )}
            </p>
            <div className="actions">
              <button type="submit" disabled={busy}>
                {t('common.save')}
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
