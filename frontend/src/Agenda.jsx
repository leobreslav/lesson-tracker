import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { AddLessonDialog, LessonMenu } from './AgendaDialogs'
import EmptyState from './EmptyState'
import CopyDialog from './CopyDialog'
import { remember, remembered, useKept } from './remember'
import { weekdayIndex } from './weekStart'
import WeekGrid from './WeekGrid'
import {
  deleteSlots,
  copySlots,
  fetchLayoutAgenda,
  createSlot,
  deleteSlot,
  fetchAgenda,
  fetchCourses,
  fetchSchoolYears,
  moveSlot,
  repeatSlot,
  updateSlot,
} from './api'
import {
  addDays,
  eachDate,
  endOfWeek,
  daysBetween,
  startOfWeek,
  today,
} from './calendarLogic'
import { dateRange, firstWeekday } from './dates'
import { MAX_LESSON_NUMBER, describeCopyResult } from './scheduleLogic'

const NUMBERS = Array.from({ length: MAX_LESSON_NUMBER }, (_, index) => index + 1)

const EMPTY = { lessons: {}, days: {} }

// «Темы уроков» переживают перезагрузку — тем же хранилищем, что флажки
// над таблицей плана: своя копия этих четырёх строк тут уже была
const TOPICS_KEY = 'agendaShowTopics'

/** Lessons from the agenda answer as a flat list, each carrying its date. */
function flatten(lessons) {
  return Object.entries(lessons).flatMap(([date, list]) =>
    list.map((item) => ({ ...item, date })),
  )
}

function studyDatesOf(days) {
  return Object.entries(days)
    .filter(([, day]) => day.is_study)
    .map(([date]) => date)
}

function lessonClassName(lesson) {
  return (
    'cell lesson' +
    (lesson.is_cancelled ? ' cancelled' : '') +
    (lesson.is_extra ? ' extra' : '') +
    // час прошёл, а записи за ним нет: красная точка в углу. Очередь записи
    // строгая, и такой час держит всё, что после него, — увидеть его надо
    // не заходя в занятие
    (lesson.debt ? ' debt' : '') +
    // а записанный — зелёная галочка, тем же углом и теми же цветами, что в
    // таблице плана: один факт должен выглядеть одинаково везде
    (lesson.recorded ? ' recorded' : '')
  )
}

export default function Agenda({ views = null, onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  /*
   * Какая неделя открыта и какие курсы скрыты — переживает уход отсюда.
   *
   * Из расписания уходят в занятие и возвращаются «назад» браузером, а
   * страница при этом собирается заново: неделя вставала на сегодняшнюю, и
   * до октябрьской надо было долистывать снова. Живёт это во вкладке
   * (`remember.useKept`), а не в настройках: завтра утром расписание
   * открывается на сегодняшнем дне, как и должно.
   */
  const [anchor, setAnchor] = useKept('agenda.week', today())
  const [data, setData] = useState(EMPTY)
  const [years, setYears] = useState([])
  // the school timetable, only as far as «is there anything of mine in it»:
  // the button must not appear for a school that keeps no timetable
  const [classes, setClasses] = useState([])
  // список, а не `Set`: наружу он уезжает через JSON, и множество доехало
  // бы пустым
  const [hiddenIds, setHiddenIds] = useKept('agenda.hidden', [])
  const hidden = useMemo(() => new Set(hiddenIds), [hiddenIds])

  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [dialog, setDialog] = useState(null) // {type:'add'|'lesson'|'copy'|'clear', ...}
  // what already sits in the target period — purely for an exact preview
  const [targetPeriod, setTargetPeriod] = useState(EMPTY)
  // days selected in the grid: {start, end}; Shift+click drags a range
  const [selection, setSelection] = useState(null)
  // plan topics per lesson: slot_id → {title, section_title};
  // null means not loaded yet, so "no topic" is not printed for nothing
  const [topics, setTopics] = useState(null)
  const [showTopics, setShowTopics] = useState(() => remembered(TOPICS_KEY, false))

  const tempId = useRef(0)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  // the week runs from the language's first weekday: Monday in Russian,
  // Sunday in American English
  const weekStart = firstWeekday()
  /*
   * Показывается всегда неделя.
   *
   * Месяц был вторым видом той же сетки и отвечал на вопрос «в какую неделю
   * пойти», а ответ на него есть проще — поле «перейти к дате» рядом.
   * Клеток в нём вчетверо больше, а в клетке те же курс, номер и тема, так
   * что неделя читается, а месяц просматривается.
   */
  const period = useMemo(
    () => ({ start: startOfWeek(anchor, weekStart), end: endOfWeek(anchor, weekStart) }),
    [anchor, weekStart],
  )

  useEffect(() => {
    let cancelled = false

    Promise.all([fetchSchoolYears(), fetchCourses()])
      .then(([yearList, classList]) => {
        if (cancelled) return
        setYears(yearList)
        setClasses(classList)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [handleError])

  /*
   * Период, к которому относится **показанная** сетка.
   *
   * Заголовок и стрелки отвечают сразу, а сетка меняется вместе с данными:
   * дни без ответа сервера считаются неучебными, и перерисованная раньше
   * времени неделя на долю секунды становилась серой.
   */
  const [shown, setShown] = useState(period)
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(
    () =>
      fetchAgenda(period.start, period.end).then((payload) => {
        setData(payload)
        setShown(period)
        setLoaded(true)
      }),
    [period],
  )

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    load()
      .catch((err) => {
        if (!cancelled) handleError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [load, handleError])

  // topics are fetched only while shown: otherwise every week costs a request
  useEffect(() => {
    if (!showTopics) {
      setTopics(null)
      return undefined
    }

    let cancelled = false
    fetchLayoutAgenda(period.start, period.end)
      .then((payload) => {
        if (!cancelled) setTopics(payload.slots)
      })
      .catch(() => {
        // silently: a topic is a bonus, the grid must not break over it
        if (!cancelled) setTopics(null)
      })

    return () => {
      cancelled = true
    }
    // data is in the deps on purpose: editing a lesson shifts the topics
  }, [showTopics, period, data])

  const toggleTopics = (value) => {
    setShowTopics(value)
    remember(TOPICS_KEY, value)
  }

  const dates = useMemo(() => eachDate(shown.start, shown.end), [shown])

  const yearById = useMemo(
    () => new Map(years.map((year) => [year.id, year])),
    [years],
  )

  /** Classes whose school year covers this date — only they can be placed. */
  const classesFor = useCallback(
    (date) =>
      classes.filter((item) => {
        const year = yearById.get(item.year)
        return year && year.start_date <= date && date <= year.end_date
      }),
    [classes, yearById],
  )

  /**
   * Who this lesson can be given to.
   *
   * A class that already has something on this number is dropped: even a
   * cancelled lesson occupies the (class, number) pair in unique_together.
   * Another class is not blocked by that cancellation — the slot is free.
   */
  const freeClassesFor = useCallback(
    (date, number) => {
      const busyClasses = new Set(
        (data.lessons[date] || [])
          .filter((item) => item.lesson_number === number)
          .map((item) => item.course_id),
      )
      return classesFor(date).filter((item) => !busyClasses.has(item.id))
    },
    [data, classesFor],
  )

  const visibleClasses = useMemo(
    () =>
      classes.filter((item) => {
        const year = yearById.get(item.year)
        return year && year.start_date <= period.end && period.start <= year.end_date
      }),
    [classes, yearById, period],
  )

  /**
   * Courses to offer in the «show» filter.
   *
   * Only the ones with lessons in the shown period — since courses became
   * the school's, `classes` holds every course in the building, and a filter
   * listing colleagues' courses would be noise a teacher cannot act on.
   * The dialogs keep using `visibleClasses`: copying and clearing are about
   * the year, not about this week.
   */
  const filterClasses = useMemo(() => {
    const present = new Set(
      Object.values(data.lessons).flat().map((item) => item.course_id),
    )
    return visibleClasses.filter((item) => present.has(item.id))
  }, [data, visibleClasses])

  const lessonsOn = useCallback(
    (date) => (data.lessons[date] || []).filter((item) => !hidden.has(item.course_id)),
    [data, hidden],
  )

  /** An optimistic edit: draw at once, restore the old answer on failure. */
  const mutate = useCallback(
    async (lessons, request) => {
      const snapshot = data
      setError(null)
      setBusy(true)
      setData({ ...data, lessons })

      try {
        await request()
        await load()
      } catch (err) {
        setData(snapshot)
        handleError(err)
      } finally {
        setBusy(false)
      }
    },
    [data, load, handleError],
  )

  const handleAdd = ({ course, is_extra, reason, step, until }) => {
    const { date, number } = dialog
    setDialog(null)

    /*
     * Ряд уроков создаёт сервер, и оптимистично его не показать: сколько
     * дат попадёт под каникулы и сколько мест занято, знает только он.
     * Поэтому тут обычный запрос с перечитыванием, а мгновенная отрисовка
     * остаётся у одиночной клетки — той, по которой щёлкнули.
     */
    if (step) {
      runBulk(
        () => repeatSlot({ course, date, lesson_number: number, step, until }),
        // отчёт тот же, что у копирования периода: сколько создано, сколько
        // пропущено и что именно помешало
        (result) => describeCopyResult(result, t),
      )
      return
    }

    tempId.current -= 1

    const optimistic = {
      id: tempId.current,
      lesson_number: number,
      course_id: course,
      course_name: classes.find((item) => item.id === course)?.name ?? '',
      is_cancelled: false,
      is_extra,
      reason,
    }

    return mutate(
      {
        ...data.lessons,
        [date]: [...(data.lessons[date] || []), optimistic].sort(
          (a, b) => a.lesson_number - b.lesson_number,
        ),
      },
      () =>
        createSlot({
          course,
          date,
          lesson_number: number,
          is_extra,
          reason,
        }),
    )
  }

  const patchLesson = (date, lesson, fields) => {
    setDialog(null)
    return mutate(
      {
        ...data.lessons,
        [date]: data.lessons[date].map((item) =>
          item.id === lesson.id ? { ...item, ...fields } : item,
        ),
      },
      () => updateSlot(lesson.id, fields),
    )
  }

  const moveLesson = (date, lesson, fields) => {
    setDialog(null)
    // на старом месте остаётся отмена — её и рисуем сразу; новое занятие
    // может оказаться вне показанного периода, и обещать его заранее
    // значило бы обещать то, чего человек не увидит
    return mutate(
      {
        ...data.lessons,
        [date]: data.lessons[date].map((item) =>
          item.id === lesson.id
            ? { ...item, is_cancelled: true, reason: fields.reason }
            : item,
        ),
      },
      () => moveSlot(lesson.id, fields),
    )
  }

  const removeLesson = (date, lesson) => {
    setDialog(null)
    return mutate(
      {
        ...data.lessons,
        [date]: data.lessons[date].filter((item) => item.id !== lesson.id),
      },
      () => deleteSlot(lesson.id),
    )
  }

  /** Load the target period so the preview knows which numbers are taken. */
  const loadTarget = useCallback(
    ({ start, end }) => {
      if (!start || !end || end < start) return

      fetchAgenda(start, end)
        .then(setTargetPeriod)
        .catch(() => setTargetPeriod(EMPTY))
    },
    [],
  )

  const copySource = useMemo(() => {
    // the source is the whole shown period across every class: the display
    // filter does not affect copying, cancelled and extra lessons stay put
    const seen = new Set()
    const merged = []

    for (const lesson of [...flatten(data.lessons), ...flatten(targetPeriod.lessons)]) {
      if (seen.has(lesson.id)) continue
      seen.add(lesson.id)
      merged.push(lesson)
    }

    return {
      slots: merged,
      studyDates: new Set([
        ...studyDatesOf(data.days),
        ...studyDatesOf(targetPeriod.days),
      ]),
    }
  }, [data, targetPeriod])

  /** A bulk operation: run it, re-read the period, report. */
  const runBulk = async (request, describe) => {
    setDialog(null)
    setBusy(true)
    setError(null)
    setNotice(null)

    try {
      const result = await request()
      await load()
      setNotice(describe(result))
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  /** Copying: every class in one request, a subset one request per class. */
  const handleCopy = ({ target_start, target_end, mode, step, classIds }) => {
    const source = copyRange
    const everyClass = classIds.length === visibleClasses.length

    return runBulk(async () => {
      const common = {
        source_start: source.start,
        source_end: source.end,
        target_start,
        target_end,
        mode,
        step,
      }

      if (everyClass) return copySlots(common)

      const totals = { created: 0, skipped: 0, deleted: 0, conflicts: [] }
      for (const classId of classIds) {
        const part = await copySlots({ ...common, course_id: classId })
        totals.created += part.created
        totals.skipped += part.skipped
        totals.deleted += part.deleted
        totals.conflicts.push(...part.conflicts)
      }
      return totals
    }, (result) => describeCopyResult(result, t))
  }

  /**
   * Удаление ряда: этот час и все такие же до конца года.
   *
   * «Очистить период» тут было, и выбор стоял неудобный: либо тридцать
   * четыре нажатия по клеткам, либо снос всего периода вместе с чужими
   * часами. Ряд — то, чем сетку строят, им же её и разбирают.
   *
   * Границу ставит год курса: дальше него урока не бывает.
   */
  const deleteRow = (date, lesson) => {
    const year = yearById.get(
      classes.find((item) => item.id === lesson.course_id)?.year,
    )

    return runBulk(
      () =>
        deleteSlots({
          classId: lesson.course_id,
          start: date,
          end: year?.end_date ?? date,
          weekday: weekdayIndex(date),
          number: lesson.lesson_number,
          onlyRegular: true,
        }),
      (result) =>
        t('agenda.deletedRow', { count: result.deleted }) +
        (result.kept ? ' ' + t('agenda.keptRecorded', { count: result.kept }) : ''),
    )
  }

  const toggleClass = (id) =>
    setHiddenIds((current) =>
      current.includes(id)
        ? current.filter((one) => one !== id)
        : [...current, id],
    )

  const step = (direction) => setAnchor((current) => addDays(current, 7 * direction))

  /** A click on a day heading selects it, Shift+click drags a range. */
  const pickDay = (date, event) => {
    setNotice(null)
    setSelection((current) => {
      if (!event.shiftKey || !current) return { start: date, end: date }
      const bounds = [current.start, date].sort()
      return { start: bounds[0], end: bounds[1] }
    })
  }

  const inSelection = (date) =>
    selection && selection.start <= date && date <= selection.end

  const selectedDays = selection
    ? daysBetween(selection.start, selection.end) + 1
    : 0

  // with nothing selected we copy the whole shown period
  const copyRange = selection ?? { start: period.start, end: period.end }

  /**
   * The lesson topic from the plan.
   *
   * Nothing is drawn until the topics load. Once they have, and no plan
   * lesson reached this slot (there are more slots than lessons), we say so
   * plainly: otherwise "no topic" and "not shown" look the same.
   */
  const topicOf = (lesson) => {
    if (!showTopics || !topics) return null

    const topic = topics[lesson.id]
    if (!topic) {
      return <span className="cell-topic missing">{t('agenda.noTopic')}</span>
    }

    return (
      <span className="cell-topic" title={topic.title}>
        {topic.title}
      </span>
    )
  }

  /*
   * Левое нажатие ведёт в занятие, правое открывает меню.
   *
   * Разделено по частоте: в занятие ходят каждый день — журнал, тема,
   * работы, — а сетку правят реже. Раньше левое открывало меню, и попасть
   * в урок можно было только его первым пунктом: два нажатия там, где
   * достаточно одного.
   */

  const openMenu = (date, lesson, at) =>
    setDialog({ type: 'lesson', date, lesson, at })

  const openFreeCell = (date, number) => {
    if (!data.days[date]?.is_study) return
    setDialog({ type: 'add', date, number })
  }

  const dayHeadClass = (date) => {
    const day = data.days[date] || {}
    return (
      'day-head' +
      (day.is_study ? '' : ' locked') +
      (date === today() ? ' today' : '') +
      (inSelection(date) ? ' selected' : '')
    )
  }

  const renderWeek = () => (
    <WeekGrid
      dates={dates}
      days={data.days}
      numbers={NUMBERS}
      busy={busy}
      selected={inSelection}
      lessonsOn={(date) =>
        // a cancelled lesson frees the slot without leaving the screen: a
        // cell can hold both the cancellation and its replacement
        lessonsOn(date)
          .slice()
          .sort((a, b) => Number(a.is_cancelled) - Number(b.is_cancelled))
      }
      renderLesson={(lesson) => (
        <>
          <span className="cell-course">{lesson.course_name}</span>
          {topicOf(lesson)}
        </>
      )}
      lessonClassName={lessonClassName}
      lessonTitle={(lesson) =>
        [lesson.course_name, lesson.reason].filter(Boolean).join(' — ')
      }
      isFree={(inCell) => !inCell.some((item) => !item.is_cancelled)}
      onPickDay={pickDay}
      onMenu={openMenu}
      onAdd={openFreeCell}
    />
  )

  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{t('agenda.title')}</h1>
        {/* «Мои · Вся школа» — тумблер приезжает сверху: страница одна, и
            какой вид сейчас, решает она, а не сетка */}
        {views}
      </header>

      <div className="agenda-bar">
        {/* стрелка — не имя: читалка объявляла кнопку как «←», и куда она
            ведёт, было неизвестно. Подпись видимая остаётся стрелкой */}
        <button
          type="button"
          className="secondary"
          aria-label={t('agenda.prevWeek')}
          title={t('agenda.prevWeek')}
          onClick={() => step(-1)}
        >
          ←
        </button>
        <button type="button" className="secondary" onClick={() => setAnchor(today())}>
          {t('agenda.today')}
        </button>
        <button
          type="button"
          className="secondary"
          aria-label={t('agenda.nextWeek')}
          title={t('agenda.nextWeek')}
          onClick={() => step(1)}
        >
          →
        </button>

        <strong>{dateRange(period.start, period.end)}</strong>

        <input
          type="date"
          value={anchor}
          aria-label={t('agenda.goToDate')}
          onChange={(event) => event.target.value && setAnchor(event.target.value)}
        />

        <button
          type="button"
          disabled={busy || loading || !!selection}
          title={selection ? t('agenda.clearSelectionFirst') : undefined}
          onClick={() => {
            setTargetPeriod(EMPTY)
            setDialog({ type: 'copy' })
          }}
        >
          {t('agenda.copyWeek')}
        </button>
      </div>

      {selection && (
        <div className="selection-bar">
          <span>
            {t('agenda.selected', {
              days: t('common.dayCount', { count: selectedDays }),
              range: dateRange(selection.start, selection.end),
            })}
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setTargetPeriod(EMPTY)
              setDialog({ type: 'copy' })
            }}
          >
            {t('agenda.copyToPeriod')}
          </button>
          <button
            type="button"
            className="link"
            aria-label={t('common.cancel')}
            onClick={() => setSelection(null)}
          >
            ✕
          </button>
        </div>
      )}

      {/* пустое состояние держится на том, что **показано**, а не на том,
          идёт ли запрос: пока оно пряталось на время загрузки, страница
          укорачивалась на целый блок — и прокрутка съезжала в начало ровно
          так же, как от исчезавшей сетки */}
      {loaded && !visibleClasses.length && (
        <EmptyState
          title={t('agenda.empty.title')}
          actions={
            <button type="button" onClick={() => navigate('/classes')}>
              {t('agenda.empty.action')}
            </button>
          }
        >
          {t('agenda.empty.hint')}
        </EmptyState>
      )}

      {visibleClasses.length > 0 && (
        <div className="class-filter">
          <span className="hint">{t('agenda.show')}</span>
          {filterClasses.map((item) => (
            <label key={item.id} className="checkbox">
              <input
                type="checkbox"
                checked={!hidden.has(item.id)}
                onChange={() => toggleClass(item.id)}
              />
              {item.name}
            </label>
          ))}

          <label className="checkbox topics-toggle">
            <input
              type="checkbox"
              checked={showTopics}
              onChange={(event) => toggleTopics(event.target.checked)}
            />
            {t('agenda.topics')}
          </label>
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="hint" role="status">
          {notice}
        </p>
      )}

      {/*
        Сетка не исчезает, пока грузится следующая неделя.

        Раньше на время запроса она заменялась строкой «Загрузка…»:
        страница схлопывалась до нескольких сотен пикселей, браузер
        прижимал прокрутку к её новой высоте — и вернувшаяся сетка
        оказывалась пролистанной в начало. Пролистал вниз до седьмого
        урока, нажал стрелку — и ты наверху.

        Поэтому показанное остаётся на месте и только гаснет, а меняется
        вместе с данными. Строка «Загрузка…» осталась ровно для первого
        раза, когда показывать ещё нечего.
      */}
      {loaded ? (
        <div className={loading ? 'refreshing' : undefined} aria-busy={loading}>
          {renderWeek()}
          {/* оба нажатия названы словами: правая кнопка и долгое нажатие
              беззвучны — ниоткуда не видно, что они есть */}
          <p className="hint grid-hint">{t('agenda.gridHint')}</p>
        </div>
      ) : (
        <p>{t('common.loading')}</p>
      )}

      {dialog?.type === 'add' && (
        <AddLessonDialog
          date={dialog.date}
          number={dialog.number}
          classes={freeClassesFor(dialog.date, dialog.number)}
          /* докуда предлагать повтор: дальше года урока не бывает */
          yearEnd={
            yearById.get(
              freeClassesFor(dialog.date, dialog.number)[0]?.year,
            )?.end_date
          }
          busy={busy}
          onSubmit={handleAdd}
          onClose={() => setDialog(null)}
        />
      )}

      {dialog?.type === 'copy' && (
        <CopyDialog
          source={copyRange}
          slots={copySource.slots}
          studyDates={copySource.studyDates}
          classes={visibleClasses}
          busy={busy}
          title={
            selection ? t('agenda.copySelected') : t('agenda.copyWholeWeek')
          }
          note={t('agenda.copyNote')}
          onTargetChange={loadTarget}
          onSubmit={handleCopy}
          onClose={() => setDialog(null)}
        />
      )}

      {dialog?.type === 'lesson' && (
        <LessonMenu
          lesson={dialog.lesson}
          date={dialog.date}
          at={dialog.at}
          busy={busy}
          onCancel={(reason) =>
            patchLesson(dialog.date, dialog.lesson, { is_cancelled: true, reason })
          }
          onRestore={() =>
            patchLesson(dialog.date, dialog.lesson, { is_cancelled: false, reason: '' })
          }
          onDelete={() => removeLesson(dialog.date, dialog.lesson)}
          onDeleteRow={() => deleteRow(dialog.date, dialog.lesson)}
          onMove={(fields) => moveLesson(dialog.date, dialog.lesson, fields)}
          onClose={() => setDialog(null)}
        />
      )}
    </main>
  )
}
