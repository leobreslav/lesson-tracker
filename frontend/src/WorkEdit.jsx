import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import WorkForm from './WorkForm'
import { fetchWork, updateWork } from './api'

/**
 * Страница правки работы: та же форма, что в окне заведения, но во всю
 * ширину.
 *
 * Окном это было, и жаловались на него прямо: у работы, которую уже ведут,
 * полей много — задание с картинками и формулами, приложенные файлы, окно
 * времени, попытки, система оценивания, — и всё это читалось в щёлку поверх
 * списка. Заведению окно идёт (там три поля и не хочется терять список из
 * виду), правке — нет.
 *
 * Страница **своя**, а не блок на сводной таблице (`/works/:id`), и это
 * решение с ценой. Таблица отвечает на «как справились»: сводки, шкала и
 * тридцать строк класса. Форма настроек, приставленная к ней сверху,
 * отодвинула бы таблицу на второй экран у всякого, кто пришёл проверять, —
 * а приходят туда именно за этим. Цена — два адреса у одной работы, и
 * названы они по тому, что на них делают.
 *
 * Уходит отсюда всё в список работ: оттуда сюда и пришли, и там же лежит
 * остальное про работу — задачи, разбор сканов, переход к проверке.
 */
export default function WorkEdit() {
  const { id } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [work, setWork] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(
    () => fetchWork(id).then(setWork),
    [id],
  )

  useEffect(() => {
    load().catch((failure) => setError(failure.message))
  }, [load])

  const back = () => navigate('/works')

  const save = async (fields) => {
    setBusy(true)
    setError(null)
    try {
      await updateWork(id, fields)
      back()
    } catch (failure) {
      setError(failure.message)
      setBusy(false)
    }
  }

  if (!work) {
    return (
      <main className="page narrow">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page narrow">
      <header className="lesson-title-head">
        <h1>{work.title}</h1>
        <p className="hint">
          {work.course_name} · {t(`works.state.${work.state}`)}
        </p>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <section className="panel">
        {/* Страница обязана назвать себя. Заголовок над ней — название
            работы, и ровно такой же стоит над сводной таблицей: без этой
            строки два адреса одной работы различались бы только тем, что на
            них нарисовано. Тот же довод, что у шапки в панели урока */}
        <div className="panel-head">
          <h3>{t('works.edit')}</h3>
        </div>

        {/*
          «Завести по требованию» тут делать нечего: работа уже есть строкой
          в базе, и картинка с файлом ложатся прямо на неё. Заботой это было
          у окна заведения, где строки ещё нет, — и `onEnsure` отдаёт готовую
          работу, чтобы у формы был один способ спросить владельца, а не два.
        */}
        <WorkForm
          work={work}
          courseId={work.course}
          busy={busy}
          onSubmit={save}
          onEnsure={async () => work}
          onCancel={back}
        />
      </section>
    </main>
  )
}
