import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import PhotoStrip from './PhotoStrip'
import PhotoViewer from './PhotoViewer'
import { deleteAttachment, gradeStudent, uploadAttachment } from './api'

/**
 * Отметка — **выбор из шкалы**, а не набранное число.
 *
 * Полем со стрелочками это было, и форма противоречила смыслу: счётчик
 * говорит «наберите сколько угодно, соседние значения рядом», а у отметки
 * значений ровно столько, сколько в шкале, и все они известны заранее.
 * Практическая цена той формы — набранное мимо шкалы (стрелки ограничивают,
 * клавиатура нет) и лишний вопрос «а до скольки тут вообще».
 *
 * Пустой выбор снимает отметку и **не ставит ноль**: ноль — это оценка, и
 * различать их обязательно. Поэтому первая строка списка своя, а не пустая:
 * пустую строку читают как «ещё не выбрал», а тут это осознанное «снять».
 */
function MarkSelect({ value, maximum, disabled, onChange }) {
  const { t } = useTranslation()

  /*
   * Шкалу правят и после того, как отметки по ней уже стоят: опустили
   * максимум с восьми до пяти — и восьмёрка перестала быть значением
   * списка. Показать её всё равно надо. Списком без неё поставленная
   * отметка выглядит как «её нет», а сохранение сняло бы её молча — то
   * есть правка шкалы стирала бы работу проверявшего, ничего об этом не
   * сказав. Лишняя строка дешевле такой пропажи.
   */
  const marks = Array.from({ length: maximum + 1 }, (unused, mark) => mark)
  if (value !== '' && !marks.includes(Number(value))) marks.push(Number(value))

  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">{t('grading.noMark')}</option>
      {marks.map((mark) => (
        <option key={mark} value={String(mark)}>
          {mark}
        </option>
      ))}
    </select>
  )
}

/**
 * Работа одного ученика: скан, оценка и слова учителя — в одном окне.
 *
 * Это и есть строка «работа и ученик», показанная целиком. Раньше её не
 * было, и ученическое лежало по разным местам: ответы на отправках, а скану
 * и оценке жить было негде.
 *
 * Оценки ставятся всем набором сразу: у MYP критериев четыре, и
 * выставляются они за один взгляд на работу. Выбор «без отметки» снимает
 * её, а не ставит ноль — ноль это оценка, и различать их обязательно.
 *
 * Скан применяется **сразу**, а оценка и комментарий ждут «Сохранить». Так
 * же, как в панели урока: файл, ждущий кнопки, — это загрузка, которая тихо
 * не случилась.
 */
export default function GradeDialog({
  work,
  student,
  criteria,
  tasks = [],
  busy,
  onSubmit,
  onChanged,
  onClose,
}) {
  const { t } = useTranslation()
  const [marks, setMarks] = useState(() =>
    Object.fromEntries(
      criteria.map((item) => [item.id, String(student.marks[item.id] ?? '')]),
    ),
  )
  /*
   * Баллы за вопросы — вторая ось, и правятся они здесь по одной причине:
   * иначе их негде править вовсе. Ставит их либо проверка ответа, либо
   * разбор скана, и ошибку чтения — «модель увидела 8 вместо 3» — чинить
   * было нечем.
   */
  const [scores, setScores] = useState(() =>
    Object.fromEntries(
      tasks.map((item) => [item.id, String(student.scores?.[item.id] ?? '')]),
    ),
  )
  const [comment, setComment] = useState(student.comment ?? '')
  /*
   * Итог за работу, поставленный руками.
   *
   * Пусто — считает система по своим полосам, и это самый частый случай.
   * Написанное перебивает вывод: что бы ни было заложено в пороги, отвечает
   * за отметку учитель, а не таблица.
   */
  const [final, setFinal] = useState(student.grade?.by_teacher ? student.grade.label : '')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  // просмотрщик листает снимки **всей работы**: сюда приходят с вопросом «а
  // что он вообще сдал», и листается тут его тетрадь целиком
  const [viewing, setViewing] = useState(null)

  const simple = criteria.length === 1 && !criteria[0].name

  const submit = (event) => {
    event.preventDefault()
    if (busy) return

    onSubmit({
      student: student.id,
      comment,
      final,
      marks: Object.fromEntries(
        criteria.map((item) => [
          item.id,
          marks[item.id] === '' ? null : Number(marks[item.id]),
        ]),
      ),
      // пустое поле снимает балл, а не ставит ноль: ноль — это оценка, и
      // различать их обязательно, как и у критериев
      scores: Object.fromEntries(
        tasks.map((item) => [
          item.id,
          scores[item.id] === '' ? null : Number(scores[item.id]),
        ]),
      ),
    })
  }

  /**
   * Строка «работа и ученик» заводится по требованию, и скану нужен её id.
   * Пустой вызов оценки её создаёт и ничего не меняет — то самое «по
   * требованию» и есть.
   */
  const upload = async (file) => {
    if (!file) return

    setUploading(true)
    setError(null)
    try {
      const row = student.row ?? (await gradeStudent(work, { student: student.id })).id
      await uploadAttachment({ studentWork: row, file })
      await onChanged()
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  const remove = async (paper) => {
    setUploading(true)
    try {
      await deleteAttachment(paper.id)
      await onChanged()
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  const papers = student.papers ?? []

  const chooseFile = useRef(null)

  return (
    <Modal onClose={onClose} title={student.name}>
      <form onSubmit={submit}>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        {/* приложить работу можно к любой: класс писал онлайн, а сдал на
            бумаге — обычный случай, и раньше его запирал флаг */}
        <section className="papers">
            <span className="hint">{t('paper.scans')}</span>
            {/* Полоса та же, что видит ученик на своей странице, и это не
                экономия: показывай мы одно и то же двумя разными списками,
                они разъехались бы — где-то появилась бы пометка о проверке,
                где-то нет, и разговор о работе шёл бы про разные экраны.

                Приложено сюда и то, что прислал сам ученик: изображение
                его работы — одна и та же вещь, кто бы его ни принёс.
                Различается только право снять, и его решает сервер. */}
            <PhotoStrip
              photos={papers}
              onOpen={(photo) => setViewing(photo.id)}
              onRemove={busy || uploading ? null : remove}
            />
            {/* Поле выбора файла — то же, что у материалов урока и файлов
                работы: скрытый `input` и зона, которая и кнопка, и место
                для перетаскивания.

                Голым `input type="file"` это стояло, и браузер рисовал его
                сам: кнопка «Choose File» по-английски при любом языке
                интерфейса — её подпись приходит от браузера, и `t()` до неё
                не дотягивается, — своя рамка мимо всех прочих и никакого
                перетаскивания. Последнее здесь обиднее всего: сюда приходят
                со снимком тетради, только что сделанным телефоном, и тащат
                его из папки. */}
            <input
              ref={chooseFile}
              type="file"
              hidden
              aria-label={t('paper.addScan')}
              onChange={(event) => {
                upload(event.target.files?.[0])
                event.target.value = ''
              }}
            />
            <button
              type="button"
              className="dropzone"
              disabled={busy || uploading}
              onClick={() => chooseFile.current.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                upload(event.dataTransfer?.files?.[0])
              }}
            >
              {uploading ? t('works.attaching') : t('paper.dropScan')}
            </button>
          </section>

        {viewing && (
          <PhotoViewer
            photos={papers.filter((paper) => paper.viewable ?? paper.image)}
            current={viewing}
            onChanged={onChanged}
            onClose={() => setViewing(null)}
          />
        )}

        {tasks.length > 0 && (
          <section className="panel">
            <p className="hint">{t('grading.questionScores')}</p>
            <div className="score-row">
              {tasks.map((item) => (
                <label className="field-with-hint" key={item.id}>
                  {`${item.name} · 0–${item.maximum}`}
                  <MarkSelect
                    value={scores[item.id]}
                    maximum={item.maximum}
                    disabled={busy}
                    onChange={(mark) =>
                      setScores((current) => ({ ...current, [item.id]: mark }))
                    }
                  />
                </label>
              ))}
            </div>
          </section>
        )}

        {criteria.map((item) => (
          <label className="field-with-hint" key={item.id}>
            {simple
              ? t('grading.markOf', { maximum: item.maximum })
              : `${item.name} · 0–${item.maximum}`}
            <MarkSelect
              value={marks[item.id]}
              maximum={item.maximum}
              disabled={busy}
              onChange={(mark) => setMarks((current) => ({ ...current, [item.id]: mark }))}
            />
          </label>
        ))}

        {/* Итог за работу — и он же то место, где правило про отметку
            наконец записано в интерфейсе.

            Система выводит отметку из набранного по полосам школы, и это
            хороший умолчательный ответ. Но только умолчательный: работа
            бывает решена и списана, бывает на границе, где видно, что
            человек понял, — и перед родителем за отметку отвечает учитель,
            а не таблица. Поэтому поле пустое по умолчанию (считает система)
            и перебивает вывод, как только в нём что-то написано.

            Выведенное при этом стоит рядом и не прячется: учитель должен
            видеть, от чего он отступил. Спрятать значило бы превратить
            осознанное решение в незаметное расхождение.

            Раскрытая подсказка про пороги отсюда убрана — она была в форме
            работы и объясняла устройство полос, то есть отвечала на вопрос,
            которого никто не задаёт; полосы задаёт школа в своём
            справочнике. */}
        {student.grade && (
          <div className="final-grade">
            <label className="field-with-hint">
              {t('grading.finalGrade')}
              <input
                value={final}
                maxLength={40}
                placeholder={student.grade.derived ?? ''}
                disabled={busy}
                onChange={(event) => setFinal(event.target.value)}
              />
            </label>
            <p className="hint">
              {student.grade.derived
                ? t('grading.derived', { label: student.grade.derived })
                : t('grading.noDerived')}
            </p>
          </div>
        )}

        <label className="field-with-hint">
          {t('grading.comment')}
          <textarea
            rows={3}
            value={comment}
            disabled={busy}
            onChange={(event) => setComment(event.target.value)}
          />
        </label>

        {criteria.length > 0 && <p className="hint">{t('grading.emptyClears')}</p>}

        <div className="actions">
          <button type="submit" disabled={busy}>
            {t('common.save')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
