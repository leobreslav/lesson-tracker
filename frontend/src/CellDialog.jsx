import { useCallback, useEffect, useState } from 'react'
import TaskThread from './TaskThread'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import TaskBrief from './TaskBrief'
import Verdict from './Verdict'
import PhotoStrip from './PhotoStrip'
import PhotoViewer from './PhotoViewer'
import { fetchSubmissions, fetchWorkPhotos } from './api'
import { dateTime } from './dates'

/**
 * История одной ячейки: все попытки ученика по одной задаче.
 *
 * Сверху — условие и эталоны: без них проверка одной ячейки превращается в
 * «а что тут вообще спрашивали».
 *
 * Открытую ячейку опрос **не перерисовывает**: пока учитель читает ответ,
 * содержимое под курсором меняться не должно. Если ученик отправил новое,
 * окно говорит об этом строкой и кнопкой «показать» — решение остаётся за
 * учителем, а не за таймером.
 */
export default function CellDialog({ work, student, task, onChanged, onClose }) {
  const { t } = useTranslation()
  const [rows, setRows] = useState(null)
  const [fresh, setFresh] = useState(false)
  const [error, setError] = useState(null)
  // снимки **этой** задачи: их и листает просмотрщик, открытый отсюда.
  // Показать здесь всю тетрадь значило бы предложить листать то, за чем не
  // приходили: пришли разбираться с одним вопросом
  const [shots, setShots] = useState([])
  const [viewing, setViewing] = useState(null)

  const load = useCallback(
    () =>
      fetchSubmissions({ task: task.id, student: student.id }).then((result) => {
        setRows(result)
        setFresh(false)
      }),
    [task.id, student.id],
  )

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [load])

  const loadPhotos = useCallback(
    () =>
      fetchWorkPhotos(work, student.id).then((answer) =>
        setShots(
          (answer.tasks.find((one) => one.id === task.id)?.photos ?? []).filter(
            (photo) => photo.image,
          ),
        ),
      ),
    [work, student.id, task.id],
  )

  useEffect(() => {
    loadPhotos().catch((err) => setError(err.message))
  }, [loadPhotos])

  // проверка отсюда меняет таблицу под окном, поэтому о ней сообщаем наверх
  const checked = () => {
    onChanged()
    return load()
  }

  return (
    <Modal onClose={onClose} title={student.name}>

      {/* что спрашивали и что считается верным: проверяя ячейку, учитель
          сверяется с эталоном, а не вспоминает его */}
      <TaskBrief task={task} />

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {fresh && (
        <p className="hint warning">
          {t('table.newAnswer')}{' '}
          <button type="button" className="link" onClick={() => load()}>
            {t('table.show')}
          </button>
        </p>
      )}

      {rows === null ? (
        <p>{t('common.loading')}</p>
      ) : (
        <ul className="attempt-list">
          {rows.map((row, index) => (
            <li key={row.id} className={verdictClass(row, task.maximum)}>
              <div className="cells">
                <span className="attempt">
                  {t('student.work.attemptNumber', { number: index + 1 })}
                </span>
                <span className="answer">{row.answer}</span>
                <span className="hint">{dateTime(row.created_at)}</span>
              </div>
              <Verdict
                submission={row}
                maximum={task.maximum}
                onChanged={checked}
                onError={setError}
              />
            </li>
          ))}
        </ul>
      )}

      {/* Снимок решения — там же, где ответы: у одной ячейки бывают и то и
          другое, и разводить их по разным окнам значило бы заставлять
          учителя открывать два, чтобы поставить один балл. */}
      <PhotoStrip
        photos={shots}
        label={shots.length ? t('photos.taskShots') : null}
        onOpen={(photo) => setViewing(photo.id)}
      />

      {/* разговор о задаче — там же, где её разбирают */}
      <TaskThread task={task.id} student={student.id} me={null} />

      {viewing && (
        <PhotoViewer
          photos={shots}
          current={viewing}
          onChanged={() => {
            loadPhotos().catch(() => {})
            onChanged()
          }}
          onClose={() => setViewing(null)}
        />
      )}
    </Modal>
  )
}

/* Полный балл — «верно», ноль — «неверно», между ними частично: у оси одно
   имя, а вид у неё три. Балла нет вовсе — эту попытку не смотрели. */
const verdictClass = (row, maximum) => {
  if (row.mark === null || row.mark === undefined) return 'unchecked'
  if (row.mark >= maximum) return 'correct'
  return row.mark === 0 ? 'wrong' : 'partial'
}
