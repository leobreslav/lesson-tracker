import { useTranslation } from 'react-i18next'

/**
 * Витрина курсов: выбирают кликом по карточке, а не пунктом селекта.
 *
 * Приём тот же, что у витрины планов, и повторён он намеренно — вплоть до
 * классов (`showcase-list`, `showcase-line`, `showcase-item`). Курс и там и
 * тут выбирают один раз за заход, а дальше долго работают внутри выбранного;
 * два разных вида у одного действия читались бы как два разных приложения.
 *
 * Селектом это было, и селект отвечал на «чем сейчас занимаемся» — верно, но
 * только пока открыт. Закрытый, он оставляет одно имя в сером контроле, а
 * пустой (экран работ курс за человека не подставляет) читается как
 * недогрузившийся заголовок, а не как вопрос, на который ждут ответа.
 *
 * Запросов отсюда не уходит: витрина показывает и зовёт `onPick`. Что делать
 * с выбором — знает страница; у работ это адрес `?course=<id>`.
 */
export default function CourseShowcase({ courses, onPick, busy = false }) {
  const { t } = useTranslation()

  return (
    <section className="panel">
      <h3>{t('works.pickCourse.title')}</h3>
      {/* Почему выбор вообще спрашивают — строкой под заголовком, до
          карточек: сперва вопрос, потом ответы на него. */}
      <p className="hint">{t('works.pickCourse.hint')}</p>

      <ul className="showcase-list">
        {courses.map((course) => (
          <li key={course.id} className="showcase-line">
            <button
              type="button"
              className="showcase-item"
              disabled={busy}
              onClick={() => onPick(course.id)}
            >
              <b>{course.name}</b>
              {/*
                Подпись — предмет и параллель, без учителя: в этом списке
                лежат курсы **этого** человека, и его имя в каждой строке
                было бы шумом. У витрины планов иначе, потому что там рядом
                стоят курсы коллег.
              */}
              <span className="hint">
                {t('works.pickCourse.line', {
                  subject: course.subject_name || '—',
                  grade: course.grade_level ?? '—',
                })}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
