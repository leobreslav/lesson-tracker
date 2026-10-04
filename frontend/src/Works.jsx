import { useCallback, useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import EmptyState from './EmptyState'
import CourseShowcase from './CourseShowcase'
import BlankDialog from './BlankDialog'
import WorkNameDialog from './WorkNameDialog'
import { blankWork } from './WorkForm'
import {
  createWork,
  deleteWork,
  fetchCourses,
  fetchWorks,
  updateWork,
} from './api'
import { rememberChoice } from './remember'

/**
 * Работы курса: контрольные, проверочные, домашние.
 *
 * Список строками, и строка — это ссылка на страницу работы. Раскрывалась
 * она на месте, и помещалась в раскрытой половина работы; за остальным
 * уходили на две разные страницы. Теперь страница у работы одна, и список
 * только ведёт на неё.
 *
 * Состояние работы приходит с сервера. «Открыта ли» — вопрос о времени, и
 * считать его в браузере значило бы получить работу, которая на экране уже
 * открыта, а на сервере ещё нет: часы у них разные.
 */
export default function Works({ onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [search, setSearch] = useSearchParams()
  const [courses, setCourses] = useState(null)
  const [works, setWorks] = useState(null)
  const [naming, setNaming] = useState(false)
  const [blank, setBlank] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  /**
   * Курс за человека здесь **не выбирается**, и это решение, а не пропуск.
   *
   * Выбирался: сперва прошлый выбор (ключ общий с планом и журналом), а если
   * его нет — первый курс списка, то есть первый по алфавиту. Оба
   * подставляли ответ на вопрос, которого человек не задавал, и оба одинаково
   * опасны на этом экране: работы заводят, правят и **проверяют**, а
   * проверенное уходит ученикам. Экран, открывшийся на чужом курсе, выглядит
   * ровно как открывшийся на своём — тот же список, та же кнопка «Добавить».
   *
   * Прошлый выбор при этом остаётся **записанным** (`rememberChoice` ниже):
   * ключ общий, и план с журналом им пользуются по-прежнему. Разница ровно в
   * том, что этот экран его не читает: подсказать соседям, чем занимались, —
   * не то же самое, что решить за человека, что он открыл.
   */
  useEffect(() => {
    fetchCourses().then(setCourses).catch(handleError)
  }, [handleError])

  /**
   * Выбранный курс живёт **в адресе**, а не в состоянии компонента.
   *
   * Ровно та же причина, что у плана: витрина показывается при каждом заходе,
   * значит у открытого должен быть свой адрес — иначе перезагрузка отправляет
   * к выбору, «назад» браузером выходит из раздела целиком, а ссылкой «вот
   * эти работы» поделиться нечем.
   *
   * Сверяется со списком: адрес приходит снаружи и может звать курс, которого
   * у человека нет — чужой, удалённый, из вчерашней ссылки. Тогда открывается
   * витрина, а не пустой список от несуществующего курса.
   */
  const wanted = search.get('course')
  const courseId =
    (courses ?? []).find((one) => String(one.id) === wanted)?.id ?? null

  const pickCourse = (id) => {
    setSearch(id ? { course: String(id) } : {})
    if (id) rememberChoice('course', id)
  }

  /** Имя выбранного курса — им подписан список работ. */
  const courseName = (courses ?? []).find((one) => one.id === courseId)?.name ?? ''

  const reload = useCallback(
    () => (courseId ? fetchWorks(courseId).then(setWorks) : Promise.resolve()),
    [courseId],
  )

  useEffect(() => {
    setWorks(null)
    reload().catch(handleError)
  }, [reload, handleError])

  const run = async (request) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await reload()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  /**
   * Завести работу: одно название, дальше — её страница.
   *
   * Остальные поля берут умолчания (`blankWork`), и выданной работа не
   * становится: класс её не увидит, пока не нажмут «Выдать». Наполняют её на
   * её странице, туда и уводим — иначе человек, закрыв окно, остался бы
   * на списке с пустой строкой и вопросом «а где задачи».
   *
   * Мимо `run`: тот перечитывает список, а мы с него уходим — перечитывать
   * незачем, да и показывать нечего.
   */
  const createNamed = (title) => {
    setBusy(true)
    setError(null)
    createWork(blankWork({ course: courseId, title }))
      .then((work) => navigate(`/works/${work.id}`))
      .catch((err) => {
        setBusy(false)
        handleError(err)
      })
  }

  const removeWork = (work) => {
    // ответы уходят вместе с работой, поэтому спрашиваем числом, а не «точно?»
    const question = work.tasks_count
      ? t('works.deleteWithTasks', { name: work.title, count: work.tasks_count })
      : t('works.delete', { name: work.title })
    if (!window.confirm(question)) return

    run(() => deleteWork(work.id))
  }

  if (courses === null) {
    return <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
  }

  /*
    Бланк живёт у списка работ, а не в мастере разбора. Печатают его раз в год
    пачкой и **до** контрольной; мастер открывают после, со стопкой исписанных
    листов в руках, и ссылка «распечатать» там отвечала на вопрос, решённый
    неделю назад.

    Курсу он при этом не принадлежит — бланк единый на все, — поэтому строка
    стоит и на витрине, где курс ещё не выбран, и в выбранном курсе: пачку на
    год печатают, не заходя ни в один. Одна строка на оба места, чтобы текст и
    поведение не разошлись.
  */
  const blankLine = (
    <>
      <p className="hint">
        <a href="/blank.pdf" target="_blank" rel="noreferrer">
          {t('scan.printBlank')}
        </a>{' '}
        {t('scan.printBlankHint')}
      </p>
      {/* Подписи — кнопкой, а не ссылкой в конце подсказки. Ссылкой она
          читалась продолжением серого текста, и её не находили: человек
          видел бланк без подписей и искал, где их добавить. Подписать бланк
          можно и без работы: контрольную ещё не завели, а печатать пачку
          надо сегодня */}
      <p>
        <button type="button" className="secondary" onClick={() => setBlank('answer')}>
          {t('blank.withLabels')}
        </button>
      </p>
      {/* Лист баллов — для работ длиннее пятнадцати задач. Учитель ставит
          баллы на нём, а не в шапке бланка; ученик пишет на обычном бланке.
          Строка устроена так же, как у бланка: чистый лист ссылкой, подписи
          кнопкой */}
      <p className="hint">
        <a href="/mark-sheet.pdf" target="_blank" rel="noreferrer">
          {t('scan.printMarkSheet')}
        </a>{' '}
        {t('scan.printMarkSheetHint')}
      </p>
      <p>
        <button type="button" className="secondary" onClick={() => setBlank('marks')}>
          {t('blank.marksWithLabels')}
        </button>
      </p>
    </>
  )

  // пустое состояние — внутри страницы, а не вместо неё: у раздела есть
  // имя, и терять его оттого, что курсов пока нет, незачем
  return (
    <main className="page wide">
      {/*
        Дорога назад — первой строкой и у самого левого края, как у плана.

        Это не действие над работами, а выход из курса: то же, что «назад» в
        браузере, только внутри раздела. Такие ставят первыми и слева — там их
        ищут глазами, не читая строку до конца. Ведёт она на `/works` без
        курса, то есть к витрине, куда попадаешь и пунктом бара.
      */}
      {courseId && (
        <button
          type="button"
          className="link screen-back"
          onClick={() => pickCourse(null)}
        >
          {t('works.open.back')}
        </button>
      )}
      {/*
        Заголовок называет **курс**, а не раздел.

        «Работы» отвечало на вопрос «где я», и отвечало верно ровно до того,
        как курс перестали подставлять: теперь на этот адрес приходят дважды —
        к витрине и в выбранный курс, — и заголовок у обоих был одинаковый.
        Открытый курс должен быть виден с первого взгляда, потому что заводят,
        правят и проверяют долго, а выбирали его один раз в начале.

        Заголовок панели ниже после этого убран: он говорил то же самое
        («Работы курса Grade 6 Algebra») вторым заголовком под первым.
      */}
      <header className="page-header">
        <h1>
          {courseId ? (
            /*
              Имя курса выделено, а не набрано заодно с заголовком.
              «Работы курса Grade 6 Algebra» — предложение, в котором важна
              последняя треть: раздел человек и так знает, а курс он выбрал
              минуту назад и проверяет себя взглядом.

              `Trans`, а не склейка строк: правило проекта требует подстановок
              параметрами, потому что порядок слов у языков разный — русское
              «Работы курса X» и английское «Assignments for X» совпали
              случайно, а третий язык совпадать не обязан. Оборачиваемый кусок
              назван тегом прямо во фразе, и переводчик волен его подвинуть.
            */
            <Trans
              i18nKey="works.forCourse"
              values={{ name: courseName }}
              components={{ course: <span className="course-name" /> }}
            />
          ) : (
            t('nav.works')
          )}
        </h1>
      </header>

      {!courses.length ? (
        <EmptyState
          title={t('works.needCourse.title')}
          actions={
            <button type="button" onClick={() => navigate('/school/courses')}>
              {t('plan.needClass.action')}
            </button>
          }
        >
          {t('works.needCourse.hint')}
        </EmptyState>
      ) : !courseId ? (
        /*
          Курс выбирают витриной, а не селектом, — тем же приёмом, что и план.
          Селект отвечал на «чем сейчас занимаемся» верно, но только пока
          открыт; закрытый, он оставляет одно имя в сером контроле, а пустой
          читается как недогрузившийся заголовок, а не как вопрос.
        */
        <>
          {blankLine}
          <CourseShowcase courses={courses} onPick={pickCourse} busy={busy} />
        </>
      ) : (
        <>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <section className="panel">
        {/* «Новая работа» — на карточке и в правом верхнем углу.
            В шапке страницы она стояла рядом с названием курса и читалась
            действием над курсом, а заводят работу **в списке**, который тут
            же под ней. Слева на карточке она читалась бы первым, что тут
            делают, — тогда как список сперва смотрят. */}
        <div className="row end">
          <button type="button" disabled={busy} onClick={() => setNaming(true)}>
            {t('works.add')}
          </button>
        </div>
        {blankLine}
        {works === null ? (
          <p>{t('common.loading')}</p>
        ) : works.length === 0 ? (
          <p className="hint">{t('works.none')}</p>
        ) : (
          <ul className="course-list work-list">
            {works.map((work) => (
                <li key={work.id} className="course-row">
                  <div className="course-head">
                    {/*
                      Название ведёт на страницу работы, а не раскрывает
                      строку.

                      Раскрывалась она, и довод был: заглянуть «что там
                      внутри», не уходя со списка. Но внутри помещалась только
                      половина работы — задание и задачи на чтение, — а за
                      второй половиной, правкой и результатами, всё равно
                      уходили, двумя разными кнопками на две разные страницы.
                      Строка списка отвечала на «что это за работа» трижды, и
                      каждый раз не целиком.

                      Ссылка, а не кнопка с переходом: работу открывают и в
                      соседней вкладке, а средняя кнопка мыши по кнопке не
                      делает ничего.
                    */}
                    <Link className="name" to={`/works/${work.id}`}>
                      {work.title}
                    </Link>

                    {/*
                      Черновик виден в списке, а выданная работа — нет.

                      Пометка тут про **действие**, а не про свойство записи:
                      «не выдана» значит «класс её не видит, и это на вас».
                      Выданная ничего не ждёт, и плашка у неё была бы шумом в
                      каждой строке — тот же довод, по которому в строке нет
                      ни окна времени, ни числа задач.
                    */}
                    {work.state === 'draft' && (
                      <span className="badge state-draft">
                        {t('works.state.draft')}
                      </span>
                    )}

                    {/* в шапке только имя и то, что с работой делают:
                        окно, попытки и число задач — разговор о настройках,
                        и живут они там, где их правят */}
                    {/* Действия — одной группой со своим зазором: общий
                        зазор строки отделяет текст от текста, а одинаковым
                        рамкам подряд его мало, они читаются одной полосой с
                        надрезами.

                        Остались здесь только **действия**: выдать и разобрать
                        сканы. «Править» и «Проверка» были переходами, и оба
                        вели бы теперь туда же, куда название. */}
                    <div className="work-actions">
                      {/*
                        «Выдать» — первой в ряду и только у черновика.

                        Работа заводится невыданной: заводят её пустой и
                        дописывают задачи, а окно времени к этому моменту уже
                        проставлено по умолчанию — то есть окно, оставленное
                        сторожить, показало бы класу недописанное.

                        Кнопка стоит первой, потому что у черновика это
                        единственное, чего от него ждут: сканы — про работу,
                        которая уже идёт. Пропадает она вместе с выдачей: отзывать
                        выданное отдельной кнопкой мы пока не умеем, и
                        нарисованная «Отозвать» в каждой строке была бы
                        предложением сделать то, за чем не приходят.
                      */}
                      {work.state === 'draft' && (
                        <button
                          type="button"
                          className="compact"
                          disabled={busy}
                          onClick={() => run(() => updateWork(work.id, { is_released: true }))}
                        >
                          {t('works.release')}
                        </button>
                      )}

                      {/* Сканы у любой работы. Прежде кнопка была только у
                          бумажной, и это запирало обычный случай: класс писал
                          онлайн, а сдал на бумаге — или учитель завёл работу
                          пустой и принёс пачку. Резать при этом есть что
                          всегда: скан ложится на строку «работа и ученик», а
                          онлайн-ответы живут на отправках и друг другу не
                          мешают */}
                      <button
                        type="button"
                        className="secondary compact"
                        disabled={busy}
                        /* разбор сканов — своя страница: работа там на
                           полчаса, и в окне поверх списка ей было тесно */
                        onClick={() => navigate(`/works/${work.id}/scans`)}
                      >
                        {t('scan.open')}
                      </button>
                    </div>

                    <button
                      type="button"
                      className="link"
                      aria-label={t('works.delete', { name: work.title })}
                      disabled={busy}
                      onClick={() => removeWork(work)}
                    >
                      ✕
                    </button>
                  </div>
                </li>
            ))}
          </ul>
        )}
      </section>
        </>
      )}

      {blank && (
        <BlankDialog
          sheet={blank}
          fileName={blank === 'marks' ? 'mark-sheet.pdf' : 'blank.pdf'}
          onClose={() => setBlank(false)}
        />
      )}

      {naming && (
        <WorkNameDialog
          busy={busy}
          onCreate={createNamed}
          onClose={() => setNaming(false)}
        />
      )}

    </main>
  )
}
