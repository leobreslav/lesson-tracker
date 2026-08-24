import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import CellDialogBank from './CellDialogBank'
import Statement from './Statement'
import TaskDialog from './TaskDialog'
import { createTask, deleteTask, moveTask, recheckTask, updateTask } from './api'
import { remember, remembered } from './remember'

// показывать ли эталоны в списке задач: это переключатель вида, а не
// настройка работы, поэтому он помнится браузером, а не хранится в базе
const ANSWERS_KEY = 'worksShowAnswers'

/**
 * Задачи работы: список условий и всё, что с ними делают.
 *
 * **Живёт в двух местах и правит только в одном.** На странице работы это
 * рабочая поверхность: добавить ячейку, накатить условие из банка, поменять
 * порядок, закрыть ответы, удалить. В развёрнутой строке списка работ —
 * тот же список **на чтение**: заглянуть «что там в этой работе», не уходя
 * со списка. Правка там убрана намеренно: два места для одного действия —
 * ровно то, на что жаловались, когда правку работы открывали и кнопкой в
 * строке, и кнопкой под заданием.
 *
 * Компонент правит сам и сам же зовёт окна (`TaskDialog`, `CellDialogBank`):
 * иначе оба места несли бы по копии восьми обработчиков, и разошлись бы они
 * молча — как расходится в этом проекте всё, что скопировано.
 *
 * `onChanged` зовётся после каждой записи: снаружи от списка задач зависит
 * ещё и число задач в строке работы, а тут его не пересчитать.
 */
export default function TaskList({ workId, tasks, readOnly = false, onChanged }) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [editingTask, setEditingTask] = useState(null) // {task} | {task: null}
  // какой ячейке накатываем условие из банка
  const [takingInto, setTakingInto] = useState(null)
  const [showAnswers, setShowAnswers] = useState(() => remembered(ANSWERS_KEY, false))
  // сколько пустых ячеек завести разом
  const [howMany, setHowMany] = useState(5)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const run = async (request) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await onChanged()
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  const saveTask = (fields) =>
    run(() =>
      (editingTask.task
        ? updateTask(editingTask.task.id, fields)
        : createTask({ ...fields, work: workId })
      ).then(() => setEditingTask(null)),
    )

  const recheck = (task) => run(() => recheckTask(task.id).then(() => setEditingTask(null)))

  return (
    <>
      <div className="panel-head spread">
        <h3>{t('works.task.title')}</h3>
        {tasks.length > 0 && (
          <button
            type="button"
            className={showAnswers ? 'chip active' : 'chip'}
            aria-pressed={showAnswers}
            onClick={() => {
              setShowAnswers(!showAnswers)
              remember(ANSWERS_KEY, !showAnswers)
            }}
          >
            {t('works.answers')}
          </button>
        )}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {tasks.length === 0 ? (
        <p className="hint">{t('works.task.none')}</p>
      ) : (
        <ol className="task-list">
          {tasks.map((task, index) => (
            <li key={task.id}>
              {/* номер рисуем сами, а не маркером списка:
                  по нему ищут задачу глазами, и ему нужны
                  и вес, и своя колонка */}
              <span className="task-number">{task.name}.</span>
              {/* кнопки — в строке условия, а не под ней:
                  спрятанные до наведения, они иначе держат
                  за собой пустую строку в каждой задаче */}
              <div className="task-head">
                <div className="task-question">
                  {/* условие с шапкой сюжета и пометкой «это
                      пункт» — одной отрисовкой на все экраны */}
                  <Statement
                    shown={task.shown}
                    onWhole={
                      task.problem
                        ? () => navigate(`/bank/problem/${task.problem}`)
                        : undefined
                    }
                  />
                  {!task.shown?.with_stem && task.shown?.is_part && (
                    <p className="hint warning">
                      {t('works.task.stemHidden')}
                    </p>
                  )}
                  {/* закрытая ячейка — обычное состояние, а
                      не беда, поэтому пометка, а не
                      предупреждение. Стоит она в строке
                      условия, а не в кнопках: кнопки
                      спрятаны до наведения, и состояние,
                      которое видно только под курсором, —
                      это состояние, которого не видно */}
                  {!task.open_for_answers && (
                    <p className="hint">
                      {t('works.task.onPaper')}
                    </p>
                  )}
                </div>
                {!readOnly && (
                <div className="task-actions">
                <button
                  type="button"
                  className="link"
                  disabled={busy || index === 0}
                  aria-label={t('plan.up')}
                  onClick={() => run(() => moveTask(task.id, 'up'))}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="link"
                  disabled={busy || index === tasks.length - 1}
                  aria-label={t('plan.down')}
                  onClick={() => run(() => moveTask(task.id, 'down'))}
                >
                  ↓
                </button>
                <button
                  type="button"
                  className="link"
                  disabled={busy}
                  onClick={() => setEditingTask({ task })}
                >
                  {t('common.edit')}
                </button>
                {/* заполнить не руками, а готовым условием:
                    поленились искать — накатили потом */}
                <button
                  type="button"
                  className="link"
                  disabled={busy}
                  onClick={() => setTakingInto(task)}
                >
                  {t('works.task.bank')}
                </button>
                {/* открыть или закрыть ответы — поштучно:
                    «Q1 и Q2 решайте онлайн, Q3 сдайте на
                    листе» флагом работы не выражалось вовсе */}
                <button
                  type="button"
                  className="link"
                  disabled={busy}
                  onClick={() =>
                    run(() =>
                      updateTask(task.id, {
                        open_for_answers: !task.open_for_answers,
                      }),
                    )
                  }
                >
                  {t(
                    task.open_for_answers
                      ? 'works.task.closeAnswers'
                      : 'works.task.openAnswers',
                  )}
                </button>
                <button
                  type="button"
                  className="link"
                  disabled={busy}
                  aria-label={t('works.task.delete')}
                  onClick={() =>
                    window.confirm(t('works.task.deleteConfirm')) &&
                    run(() => deleteTask(task.id))
                  }
                >
                  ✕
                </button>
                </div>
                )}
              </div>

              {showAnswers && (
                <div className="answers">
                  {task.answers.length === 0 ? (
                    <span className="hint">
                      {t('works.task.noAnswers')}
                    </span>
                  ) : (
                    task.answers.map((answer, position) => (
                      <span className="tag" key={position}>
                        {answer}
                      </span>
                    ))
                  )}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}

      {/* «добавить» — последняя строка списка, а не третья
          кнопка в стороне: добавляют после последней задачи,
          там ей и место.

          Кнопок здесь было две: «Добавить задачу» и «пустая
          ячейка» рядом. Отвечали они на один вопрос — «нужна
          ещё одна ячейка» — и различались только тем, зайдёт
          ли человек в окно. То есть вторая кнопка была не
          отдельным действием, а обходом окна, которое не
          отпускало без условия. Отпускать его научили
          (`TaskDialog`), и обход стал не нужен: пустая ячейка
          заводится тем же путём, что и всякая другая, —
          нажать «Сохранить», ничего не заполнив. */}
      {!readOnly && (
      <div className="row middle">
        <button
          type="button"
          className="task-add"
          disabled={busy}
          onClick={() => setEditingTask({ task: null })}
        >
          + {t('works.task.add')}
        </button>

        {/*
          * Пачкой — потому что бумажную работу заводят целиком.
          *
          * Ячейка на бланке пустая по определению: условие лежит на листе
          * условий, а в системе от неё нужен только номер и цена. Пятнадцать
          * таких заводились пятнадцатью открытыми окнами, и это не мелочь —
          * ровно на этом месте люди бросают и идут вписывать баллы руками.
          */}
        <input
          type="number"
          min="1"
          max="15"
          value={howMany}
          disabled={busy}
          aria-label={t('works.task.blankCount')}
          onChange={(event) =>
            setHowMany(Math.min(15, Math.max(1, Number(event.target.value) || 1)))
          }
        />
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() =>
            run(async () => {
              // по одной и по очереди: позиция ячейки — это её место в
              // списке, и параллельные записи разложили бы их как придётся
              for (let i = 0; i < howMany; i += 1) {
                await createTask({ work: workId })
              }
            })
          }
        >
          {t('works.task.addBlank', { count: howMany })}
        </button>
      </div>
      )}

      {takingInto && (
        <CellDialogBank
          task={takingInto}
          answered={tasks.find((one) => one.id === takingInto.id)?.answered ?? 0}
          onClose={() => setTakingInto(null)}
          onDone={() => {
            setTakingInto(null)
            run(() => Promise.resolve())
          }}
        />
      )}

      {editingTask && (
        <TaskDialog
          task={editingTask.task}
          busy={busy}
          onSubmit={saveTask}
          onRecheck={recheck}
          onClose={() => setEditingTask(null)}
        />
      )}
    </>
  )
}
