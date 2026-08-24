import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import ScanWizard from './ScanWizard'
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
 * | название | заголовком страницы, правится кликом по нему | оно же и есть имя страницы |
 * | задание | во весь экран, поле на дюжину строк | его пишут, переписывают и правят весь год |
 * | файлы | под заданием | прикладывают в тот же заход |
 * | задачи | своей карточкой ниже | вторая половина той же работы |
 * | окно, попытки, показ отметки, итоговая, оценивание | за кнопкой «Настройки» | задают один раз и не трогают |
 *
 * **Название на странице одно.** Поле «Название» стояло в карточке
 * содержания — то есть под заголовком страницы, показывавшим ровно тот же
 * текст, и вдобавок под жирной подписью «Пояснения к работе», к которой оно
 * не имело отношения. Один текст в двух местах читается как ошибка вёрстки
 * и заставляет гадать, какое из двух настоящее.
 *
 * Теперь оно правится кликом по заголовку — как тема на странице занятия и
 * как строка в таблице плана: одна операция не должна делаться тремя
 * разными способами на трёх экранах. Оттуда же и порядок сохранения:
 * переименование применяется сразу, своей маленькой формой, — заголовок
 * страницы не бывает черновиком.
 *
 * **Просмотр — тумблер, а не второе поле рядом.** Задание это Markdown с
 * формулами и картинками, и посмотреть его глазами ученика надо; но поле и
 * вид бок о бок делят пополам ровно ту ширину, ради которой правку и унесли
 * из окна. Тумблер тот же, что в панели урока и в окне задачи.
 *
 * Сохраняется здесь три вещи **по-разному**, и это не небрежность: задание
 * — черновик до «Сохранить» (текст правят долго и возвращаются к нему), а
 * название, файлы, задачи и настройки — строки в базе, и применяются сразу.
 * Файл, ждущий кнопки, — это загрузка, которая тихо не случилась.
 */
export default function WorkEdit() {
  const { id } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [work, setWork] = useState(null)
  const [impact, setImpact] = useState(null)
  const [tasks, setTasks] = useState([])
  const [form, setForm] = useState(null)
  const [renaming, setRenaming] = useState(null)
  const [preview, setPreview] = useState(false)
  const [settings, setSettings] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(
    () =>
      fetchWork(id).then((answer) => {
        setWork(answer)
        // черновик заводится один раз, при загрузке: перечитывание после
        // правки задач не должно затирать набранный, но не сохранённый текст
        setForm((current) => current ?? { description: answer.description ?? '' })
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

  const dirty = work && form && form.description !== (work.description ?? '')

  const save = async (event) => {
    event.preventDefault()
    if (busy) return

    setBusy(true)
    setError(null)
    try {
      setWork(await updateWork(id, { description: form.description }))
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  const rename = async (event) => {
    event.preventDefault()
    if (busy || !renaming.trim()) return

    setBusy(true)
    setError(null)
    try {
      setWork(await updateWork(id, { title: renaming.trim() }))
      setRenaming(null)
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
          {/* Переименование — кликом по названию, как на странице занятия и
              как в таблице плана. Своей строкой формы оно и сохраняется:
              заголовок страницы черновиком не бывает */}
          {renaming === null ? (
            <h1>
              <button
                type="button"
                className="link name"
                title={t('works.rename')}
                disabled={busy}
                onClick={() => setRenaming(work.title)}
              >
                {work.title}
              </button>
            </h1>
          ) : (
            <form className="row" onSubmit={rename}>
              <input
                autoFocus
                value={renaming}
                maxLength={200}
                aria-label={t('works.workTitle')}
                placeholder={t('works.workTitle')}
                onChange={(event) => setRenaming(event.target.value)}
              />
              <button type="submit" disabled={busy || !renaming.trim()}>
                {t('common.save')}
              </button>
              <button type="button" className="secondary" onClick={() => setRenaming(null)}>
                {t('common.cancel')}
              </button>
            </form>
          )}

          <p className="hint">
            {work.course_name} · {t(`works.state.${work.state}`)}
          </p>
        </div>

        <div className="row">
          {/* Сканы — там же, где и всё, что делают с работой целиком. Кнопка
              жила только в списке работ, и это значило вот что: учитель,
              открывший работу, чтобы завести под бланк пятнадцать ячеек,
              должен был уйти со страницы обратно в список, чтобы принести
              туда пачку. Одна работа — одно место, откуда с ней работают. */}
          <button type="button" className="secondary" onClick={() => setScanning(true)}>
            {t('scan.open')}
          </button>

          {/* Настройки — кнопкой, и стоит она у заголовка, а не над заданием:
              рядом с текстом она читалась бы как что-то, что с этим текстом
              делают */}
          <button type="button" className="secondary" onClick={() => setSettings(true)}>
            {t('works.settings')}
          </button>
        </div>
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

      {/* Карточка названа по тому, что в ней лежит целиком — задание и
          файлы к нему. Называлась она «Пояснения к работе», то есть именем
          одного из двух своих полей, и подпись этого поля повторяла
          заголовок строкой ниже */}
      <section className="panel">
        <div className="panel-head spread">
          <h3>{t('works.content')}</h3>
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
            withTitle={false}
          />

          <div className="actions">
            <button type="submit" disabled={busy || !dirty}>
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

      {scanning && (
        <ScanWizard
          work={work}
          /* Перечитываем и на закрытии, не только на «применить»: мастер
             заводит ячейки первым же шагом, и закрытый на полпути он оставлял
             бы на экране прежний список задач. */
          onClose={() => {
            setScanning(false)
            loadTasks()
          }}
          onDone={() => loadTasks()}
        />
      )}

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
