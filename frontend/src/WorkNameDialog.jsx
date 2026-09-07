import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'

/**
 * Окно заведения работы: спрашивает **одно название**.
 *
 * Спрашивало оно название и две даты, а формой было той же, что и правка,
 * только поверх списка. Довод был разумный: уводить со списка ради трёх полей
 * — терять место, куда человек смотрел.
 *
 * Но работу заводят, чтобы её **наполнить**: дописать задание, задачи,
 * эталоны, — и всё это живёт на странице правки. То есть после «Сохранить»
 * человек всё равно уходил туда, только сперва заполнив три поля в щёлке.
 * Окно из шага работы превратилось в заставку перед ней.
 *
 * Поэтому здесь остался вопрос, на который без человека не ответить, — как
 * работу назвать, — а всё остальное берут умолчания (`blankWork`). Сразу
 * после создания открывается страница правки: там и продолжают.
 *
 * Выданной работа при этом не становится: класс её не увидит, пока учитель не
 * нажмёт «Выдать». Раньше эту роль играло окно времени, и играло плохо — оно
 * показывало работу, когда наступал момент, проставленный по умолчанию.
 */
export default function WorkNameDialog({ busy, onClose, onCreate }) {
  const { t } = useTranslation()
  const [title, setTitle] = useState('')

  const submit = (event) => {
    event.preventDefault()
    if (busy || !title.trim()) return
    onCreate(title)
  }

  return (
    <Modal onClose={onClose} title={t('works.add')}>
      <form onSubmit={submit}>
        <label className="field-with-hint">
          {t('works.workTitle')}
          <input
            autoFocus
            value={title}
            disabled={busy}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>

        {/* Сказано заранее, что будет дальше: окно закроется, и человек
            окажется на другом экране. Переход без предупреждения читается как
            «меня куда-то унесло», особенно когда его не просили. */}
        <p className="hint">{t('works.addHint')}</p>

        <div className="actions">
          <button type="submit" disabled={busy || !title.trim()}>
            {t('works.addAction')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
