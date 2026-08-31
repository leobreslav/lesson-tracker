import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Витрина планов: четыре области, две оси, один вопрос.
 *
 * Планов у человека четыре вида, и до сих пор они лежали в трёх разных
 * местах: свои курсы и поднадзорные — кнопками в пустом состоянии, курсы
 * школы — группой селекта, полка — окном «Из библиотеки», причём чужие
 * записи с полки не предлагались вовсе. Найти «тот самый план» значило
 * помнить, каким из трёх способов он открывается, — то есть держать в
 * голове устройство экрана, а не свою работу.
 *
 * Оси именно две, и они независимы:
 *
 * - **есть ли курс.** План курса живёт в календаре: у него даты, расписание
 *   и утверждение методистом. План на полке — программа без года и без
 *   класса. Это разные вещи, а не два состояния одной;
 * - **мой ли он.** Свой правят, чужой читают. Роль принадлежит человеку, а
 *   не записи, — то же решение, по которому группы селекта разделены
 *   `optgroup`'ом, а не значком у курса.
 *
 * Поэтому слева то, что с курсом, справа — то, что без; сверху своё, снизу
 * чужое. Порядок в разметке — построчный (моё-курс, моё-полка, чужое-курс,
 * чужое-полка), и это важнее сетки: на телефоне колонка одна, сетка
 * схлопывается, а «сначала моё, потом чужое» остаётся. Заголовок у каждой
 * области называет **обе** оси разом («Мои планы на полке»), а не одну, —
 * иначе, схлопнувшись, области перестали бы отличаться друг от друга.
 *
 * **Заголовок стоит и над пустой областью.** «Планов коллег на полке пока
 * нет» — это ответ; отсутствие области ответом не является, и человек
 * остаётся гадать, то ли их нет, то ли экран их не показывает. Тот же
 * расчёт, что у групп полки в окне библиотеки.
 *
 * Сужение — одно на всю витрину, и списки его вариантов строятся **по
 * всему набору**, а не по уже сужённому: выбранный предмет вычистил бы из
 * соседнего списка все годы, кроме своих, и вернуться к «любому» стало бы
 * нечем. Тот же расчёт, что в `LibraryDialog` и `CoursePicker`.
 *
 * Запросов отсюда не уходит ни одного: витрина только показывает и зовёт
 * `onPick`. Что делать с выбором — знает страница, и знает по-разному: у
 * курса свой адрес, у заготовки свой.
 */

/** Порядок областей: построчно, и он же — порядок на телефоне. */
const AREAS = [
  { key: 'mineCourses', mine: true, kind: 'course' },
  { key: 'mineTemplates', mine: true, kind: 'template' },
  { key: 'otherCourses', mine: false, kind: 'course' },
  { key: 'otherTemplates', mine: false, kind: 'template' },
]

export default function PlanShowcase({ items, onPick, onCreate, busy = false }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [teacher, setTeacher] = useState('')
  const [subject, setSubject] = useState('')
  const [grade, setGrade] = useState('')

  /** Что вообще есть на витрине — по всему набору, а не по сужённому. */
  const options = useMemo(() => {
    const teachers = [
      ...new Set(items.map((item) => item.teacher).filter(Boolean)),
    ].sort((a, b) => a.localeCompare(b))
    const subjects = [
      ...new Set(items.map((item) => item.subjectName).filter(Boolean)),
    ].sort((a, b) => a.localeCompare(b))
    const grades = [
      ...new Set(items.map((item) => item.gradeLevel).filter(Boolean)),
    ].sort((a, b) => a - b)
    return { teachers, subjects, grades }
  }, [items])

  const found = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return items.filter(
      (item) =>
        (!teacher || item.teacher === teacher) &&
        (!subject || item.subjectName === subject) &&
        (!grade || String(item.gradeLevel) === grade) &&
        (!needle || item.name.toLowerCase().includes(needle)),
    )
  }, [items, query, teacher, subject, grade])

  const areas = AREAS.map((area) => ({
    ...area,
    items: found.filter(
      (item) => item.mine === area.mine && item.kind === area.kind,
    ),
  }))

  /**
   * Подпись строки — одним ключом со всеми частями, а не склейкой.
   *
   * Недостающее заменяется прочерком, как в подписи полки: пустое место в
   * середине строки читается как обрыв, а прочерк — как «неизвестно».
   */
  const line = (item) =>
    t('plan.showcase.line', {
      subject: item.subjectName || '—',
      grade: item.gradeLevel ?? '—',
      who: item.teacher || '—',
    })

  return (
    <section className="panel plan-showcase">
      <h3>{t('plan.showcase.title')}</h3>
      <p className="hint">{t('plan.showcase.hint')}</p>

      {/*
        «Написать новый план…» стоит над витриной и виден всегда — в том
        числе когда все четыре области пусты. Это ровно тот человек, ради
        которого дверь и заведена: курса ему не поручили, а программу он
        писать вправе, и другого входа к плану без курса у него нет.
      */}
      <div className="row">
        <button type="button" disabled={busy} onClick={onCreate}>
          {t('plan.shelf.create')}
        </button>
      </div>

      {items.length > 0 && (
        <div className="row">
          <input
            type="search"
            value={query}
            placeholder={t('library.search')}
            aria-label={t('library.search')}
            onChange={(event) => setQuery(event.target.value)}
          />
          {/*
            Учитель — первым из трёх, и он тут не для симметрии.

            «Найти план Петровой по геометрии» — измеренная нужда: у завуча
            в школе несколько десятков курсов, и глазами это не читают. До
            витрины сужение по учителю стояло у селекта в шапке; переехало
            сюда вместе с самим поиском плана, иначе на экране остались бы
            два места, спрашивающих одно и то же.
          */}
          {options.teachers.length > 1 && (
            <select
              className="course-filter"
              value={teacher}
              aria-label={t('plan.filters.anyTeacher')}
              onChange={(event) => setTeacher(event.target.value)}
            >
              <option value="">{t('plan.filters.anyTeacher')}</option>
              {options.teachers.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          )}
          {options.subjects.length > 1 && (
            <select
              className="course-filter"
              value={subject}
              aria-label={t('plan.filters.anySubject')}
              onChange={(event) => setSubject(event.target.value)}
            >
              <option value="">{t('plan.filters.anySubject')}</option>
              {options.subjects.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          )}
          {options.grades.length > 1 && (
            <select
              className="course-filter"
              value={grade}
              aria-label={t('library.anyGrade')}
              onChange={(event) => setGrade(event.target.value)}
            >
              <option value="">{t('library.anyGrade')}</option>
              {options.grades.map((level) => (
                <option key={level} value={String(level)}>
                  {t('library.gradeOption', { grade: level })}
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      <div className="showcase-grid">
        {areas.map((area) => (
          <section key={area.key} className="showcase-area">
            <h4>{t(`plan.showcase.groups.${area.key}`)}</h4>
            {area.items.length === 0 ? (
              <p className="hint">{t(`plan.showcase.none.${area.key}`)}</p>
            ) : (
              <ul className="showcase-list">
                {area.items.map((item) => (
                  <li key={`${item.kind}-${item.id}`}>
                    {/*
                      Не `button.link`: та в этом проекте серая и краснеет
                      на наведении — идиома «убрать», а не «перейти». Здесь
                      переход, и выглядеть он должен переходом.
                    */}
                    <button
                      type="button"
                      className="showcase-item"
                      disabled={busy}
                      onClick={() => onPick(item)}
                    >
                      <b>{item.name}</b>
                      <span className="hint">{line(item)}</span>
                      {/*
                        Пометка — только там, где она про действие, а не про
                        свойство записи. «Ждёт решения» зовёт открыть курс
                        сейчас; «черновик» отвечает на вопрос, который у
                        своей записи на полке возникает всегда: видит ли это
                        кто-нибудь, кроме меня.
                      */}
                      {item.waiting && (
                        <span className="badge waiting">
                          {t('plan.role.deciding')}
                        </span>
                      )}
                      {item.draft && (
                        <span className="badge">{t('library.draft')}</span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>

      {items.length > 0 && found.length === 0 && (
        <p className="hint">{t('library.nothingFound')}</p>
      )}
    </section>
  )
}
