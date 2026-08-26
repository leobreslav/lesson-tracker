import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import CoursePicker from './CoursePicker'
import EmptyState from './EmptyState'
import JournalTable from './JournalTable'
import WorkDialog from './WorkDialog'
import {
  createWork,
  fetchCourses,
  fetchJournal,
  gradeStudent,
  markAttendance,
  updateWork,
} from './api'
import { applyAttendance, applyGrade } from './journalLayout'
import { lastChoice, rememberChoice, useKept } from './remember'

/**
 * Журнал курса: как идут дела у класса — одним экраном.
 *
 * Экрана этого не было, а вопрос задают чаще прочих: на собрании, на педсовете
 * и просто в конце четверти. Ответ до сих пор был разложен по страницам работ:
 * тридцать переходов вместо одного взгляда, и посещаемость при этом жила ещё и
 * на третьем экране — внутри занятия.
 *
 * **Терм, а не год.** За год у курса от тридцати до семидесяти занятий, и всё
 * это в одну таблицу лезет только с горизонтальной прокруткой; таблица, в
 * которую въезжают стрелками, отвечает на вопрос хуже, чем таблица, в которую
 * попадают глазами. Год целиком остаётся отдельной кнопкой — он отвечает на
 * другой вопрос: не «как идёт четверть», а «как прошёл год».
 *
 * Выбранный терм переживает уход со страницы и возврат назад, но не закрытие
 * вкладки: это поза за работой, а не настройка. Тот же `useKept`, что у
 * недели в расписании.
 */
export default function Journal({ onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [courses, setCourses] = useState(null)
  const [courseId, setCourseId] = useState(null)
  const [term, setTerm] = useKept('journalTerm', null)
  const [journal, setJournal] = useState(null)
  const [error, setError] = useState(null)
  // столбец, на который заводят работу, и она сама — если её уже успела
  // завести вставленная картинка (см. `WorkForm`)
  const [adding, setAdding] = useState(null)
  const [draft, setDraft] = useState(null)
  const [busy, setBusy] = useState(false)
  const [version, setVersion] = useState(0)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  useEffect(() => {
    fetchCourses()
      .then((list) => {
        setCourses(list)
        // ключ выбора общий с планом и работами: работают обычно в одном курсе
        setCourseId((current) => {
          const remembered = lastChoice('course')
          const known = (id) => list.some((item) => item.id === id)
          if (current && known(current)) return current
          if (known(remembered)) return remembered
          return list[0]?.id ?? null
        })
      })
      .catch(handleError)
  }, [handleError])

  useEffect(() => {
    if (!courseId) return
    // заведённая работа меняет шапку столбца, а не только список работ:
    // перечитываем весь журнал, потому что второй расчёт того же в браузере
    // разошёлся бы с серверным — тем самым, что рисует таблицу
    void version
    setJournal(null)
    /*
     * `term === null` — «решай сам»: сервер откроет ту четверть, в которой
     * идёт сегодняшний день, а в каникулы — прошедшую. Обратно в состояние
     * это не записывается намеренно: запиши — и выбор человека стал бы
     * неотличим от умолчания, а назавтра страница открылась бы во вчерашней
     * четверти, которую никто не выбирал. Подсвечивается поэтому то, что
     * **ответил сервер** (`journal.term`), а не то, что мы просили.
     */
    fetchJournal(courseId, term).then(setJournal).catch(handleError)
  }, [courseId, term, version, handleError])

  if (courses === null) {
    return (
      <main className="page wide">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  /*
   * Смена курса **забывает четверть**, и это не мелочь уборки. Курс бывает
   * из другого года, а четверти принадлежат году: выбранная «2 четверть»
   * прошлого курса в новом не значит ничего. Сервер такую просьбу переживает
   * (ответит умолчанием), но продолжать её слать значило бы просить каждый
   * раз то, чего у этого курса нет.
   */
  const pickCourse = (id) => {
    if (id !== courseId) setTerm(null)
    setCourseId(id)
    rememberChoice('course', id)
  }

  const terms = journal?.terms ?? []

  /*
   * Оценка ставится **в клетке**, и записывается она той же дверью, что и в
   * окне проверки (`POST /api/works/<id>/grade/`): вторая дверь к тому же
   * значению разошлась бы с первой в первой же правке. Пустая строка снимает
   * итог и возвращает работу системе — это не ноль.
   *
   * Ответ кладётся в журнал как есть, **без пересчёта**: отметку выводит
   * сервер (`services.final_grade`), и второй такой же расчёт в браузере
   * разошёлся бы с ним молча. Перечитывать весь журнал на каждую оценку
   * дорого и незачем — меняется одна клетка.
   */
  const setGrade = async (work, studentId, text) => {
    try {
      const answer = await gradeStudent(work.id, {
        student: studentId,
        final: text,
      })
      setJournal((now) =>
        now ? applyGrade(now, work.id, studentId, answer.grade) : now,
      )
    } catch (failure) {
      handleError(failure)
    }
  }

  /* Присутствие — своя дверь (`POST /api/slots/<id>/attendance/`), потому что
     это запись о занятии, а не об оценке. `status: null` снимает отметку:
     строка удаляется, состояние возвращается в «не отмечено». */
  const setAttendance = async (slotId, studentId, status) => {
    try {
      await markAttendance(slotId, [{ student: studentId, status }])
      setJournal((now) =>
        now ? applyAttendance(now, slotId, studentId, status) : now,
      )
    } catch (failure) {
      handleError(failure)
    }
  }

  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{t('journal.title')}</h1>
        <CoursePicker courses={courses} value={courseId} onChange={pickCourse} />

        {/* Четверть — рядом с курсом и тем же контролом, что сужение в
            расписании: это не отдельная полоса над таблицей, а вторая половина
            вопроса «чей журнал и за какой срок».

            Выбранным показывается то, что **ответил сервер** (`journal.term`),
            а не то, что мы просили: `null` в запросе значит «решай сам», и
            подменять его своей догадкой значило бы показать выбор, которого
            никто не делал. */}
        {terms.length > 0 && (
          <select
            className="course-filter"
            aria-label={t('journal.term')}
            value={journal && journal.term === null ? 'all' : (journal?.term ?? '')}
            onChange={(event) => setTerm(event.target.value)}
          >
            {terms.map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
            {/* «весь год» — не пятая четверть, а другой вопрос: не «как идёт
                четверть», а «как прошёл год» */}
            <option value="all">{t('journal.wholeYear')}</option>
          </select>
        )}
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!courses.length ? (
        <EmptyState
          title={t('journal.needCourse.title')}
          actions={
            <button type="button" onClick={() => navigate('/school/courses')}>
              {t('plan.needClass.action')}
            </button>
          }
        >
          {t('journal.needCourse.hint')}
        </EmptyState>
      ) : (
        <>
          <section className="panel">
            {journal === null ? (
              <p className="hint">{t('common.loading')}</p>
            ) : journal.students.length === 0 ? (
              <p className="hint">{t('journal.noStudents')}</p>
            ) : (
              <JournalTable
                journal={journal}
                onAddWork={(column) => {
                  setDraft(null)
                  setAdding(column)
                }}
                onSetGrade={setGrade}
                onSetAttendance={setAttendance}
              />
            )}
          </section>
        </>
      )}

      {/* Работа заводится **на столбец**, то есть с готовым занятием: журнал
          — то место, где видно пустую клетку, и уходить отсюда, чтобы её
          заполнить, было единственной дорогой. Форма та же самая, что на
          странице урока и в списке работ: вторая, «быстрая», разошлась бы с
          ней в первой же правке. */}
      {adding && (
        <WorkDialog
          work={draft}
          courseId={courseId}
          slot={adding.slot}
          busy={busy}
          onEnsure={async (fields) => {
            const created = await createWork(fields)
            setDraft(created)
            return created
          }}
          onSubmit={async (fields) => {
            setBusy(true)
            setError(null)
            try {
              await (draft ? updateWork(draft.id, fields) : createWork(fields))
              setAdding(null)
              setDraft(null)
              setVersion((now) => now + 1)
            } catch (failure) {
              handleError(failure)
            } finally {
              setBusy(false)
            }
          }}
          onClose={() => {
            setAdding(null)
            setDraft(null)
            // картинка в задании заводит работу до «Сохранить»: закрыли
            // окно — она уже есть, и журнал должен её показать
            if (draft) setVersion((now) => now + 1)
          }}
        />
      )}
    </main>
  )
}
