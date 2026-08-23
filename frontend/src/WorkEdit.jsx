import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import Switch from './Switch'
import TaskList from './TaskList'
import WorkContent from './WorkContent'
import WorkSettingsDialog from './WorkSettingsDialog'
import { fetchTasks, fetchWork, fetchWorkImpact, updateWork } from './api'

/**
 * Страница работы: задание, файлы и задачи — всё, из чего работа состоит.
 *
 * Окном это было, и жаловались дважды. Сперва на то, что правка вообще
 * открывается окном: полей полтора десятка, и читались они в щёлку поверх
 * списка. Потом — на то, что и на странице всё лежало вперемешку: окно
 * времени, попытки и три флажка стояли выше задания, то есть выше главного.
 *
 * Отсюда раскладка, и она вся из одного правила: **на виду то, что
 * переписывают, за кнопкой то, что задают однажды.**
 *
 * | | где | почему |
 * |---|---|---|
 * | задание | во весь экран, поле на дюжину строк | его пишут, переписывают и правят весь год |
 * | файлы | под заданием | прикладывают в тот же заход |
 * | задачи | своей карточкой ниже | вторая половина той же работы |
 * | окно, попытки, показ отметки, итоговая, оценивание | за кнопкой «Настройки» | задают один раз и не трогают |
 *
 * **Просмотр — тумблер, а не второе поле рядом.** Задание это Markdown с
 * формулами и картинками, и посмотреть его глазами ученика надо; но поле и
 * вид бок о бок делят пополам ровно ту ширину, ради которой правку и унесли
 * из окна. Тумблер тот же, что в панели урока и в окне задачи.
 *
 * Три вещи сохраняются здесь **по-разному**, и это не небрежность:
 * название с заданием — черновик до «Сохранить» (текст правят долго и
 * возвращаются к нему), а файлы, задачи и настройки — строки в базе, и
 * применяются сразу. Файл, ждущий кнопки, — это загрузка, которая тихо не
 * случилась.
 */
export default function WorkEdit() {
  const { id } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [work, setWork] = useState(null)
  const [impact, setImpact] = useState(null)
  const [tasks, setTasks] = useState([])
  const [form, setForm] = useState(null)
  const [preview, setPreview] = useState(false)
  const [settings, setSettings] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(
    () =>
      fetchWork(id).then((answer) => {
        setWork(answer)
        // черновик заводится один раз, при загрузке: перечитывание после
        // правки задач не должно затирать набранный, но не сохранённый текст
        setForm((current) =>
          current ?? { title: answer.title, description: answer.description ?? '' },
        )
      }),
    [id],
  )

  const loadTasks = useCallback(() => fetchTasks(id).then(setTasks), [id])

  useEffect(() => {
    load().catch((failure) => setError(failure.message))
    loadTasks().catch((failure) => setError(failure.message))
    // Цена правки: сколько человек уже решает и сколько ответов дано.
    // Запрета нет — опечатку в условии находят посреди урока, и запрет тут
    // дороже ошибки, — но молчать нельзя: правка вслепую ломает то, что
    // люди пишут прямо сейчас. Место предупреждению здесь, а не в форме
    // заведения: там отвечать на работу ещё некому
    fetchWorkImpact(id).then(setImpact).catch(() => setImpact(null))
  }, [id, load, loadTasks])

  const dirty =
    work &&
    form &&
    (form.title !== work.title || form.description !== (work.description ?? ''))

  const save = async (event) => {
    event.preventDefault()
    if (busy || !form.title.trim()) return

    setBusy(true)
    setError(null)
    try {
      setWork(await updateWork(id, { title: form.title.trim(), description: form.description }))
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  if (!work || !form) {
    return (
      <main className="page wide">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page wide">
      <header className="page-header">
        <div className="lesson-title-head">
          <h1>{work.title}</h1>
          <p className="hint">
            {work.course_name} · {t(`works.state.${work.state}`)}
          </p>
        </div>

        {/* Настройки — кнопкой, и стоит она у заголовка, а не над заданием:
            рядом с текстом она читалась бы как что-то, что с этим текстом
            делают */}
        <button type="button" className="secondary" onClick={() => setSettings(true)}>
          {t('works.settings')}
        </button>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {impact?.answers > 0 && (
        <p className="hint warning">
          {t('works.impact', { answers: impact.answers, students: impact.students })}
        </p>
      )}

      <section className="panel">
        <div className="panel-head spread">
          <h3>{t('works.description')}</h3>
          <Switch
            className="compact"
            value={preview ? 'preview' : 'write'}
            label={t('lesson.viewMode')}
            options={[
              { value: 'write', label: t('lesson.edit') },
              { value: 'preview', label: t('lesson.preview') },
            ]}
            onChange={(mode) => setPreview(mode === 'preview')}
          />
        </div>

        <form onSubmit={save}>
          <WorkContent
            form={form}
            setForm={setForm}
            ensureWork={async () => work.id}
            initialFiles={work.files ?? []}
            busy={busy}
            preview={preview}
            rows={14}
          />

          <div className="actions">
            <button type="submit" disabled={busy || !dirty || !form.title.trim()}>
              {t('common.save')}
            </button>
            <span className="hint" role="status">
              {dirty ? t('lesson.unsaved') : t('lesson.allSaved')}
            </span>
          </div>
        </form>
      </section>

      <section className="panel">
        <TaskList workId={work.id} tasks={tasks} onChanged={loadTasks} />
      </section>

      {settings && (
        <WorkSettingsDialog
          work={work}
          onSaved={(saved) => {
            setWork(saved)
            setSettings(false)
          }}
          onClose={() => setSettings(false)}
        />
      )}
    </main>
  )
}
