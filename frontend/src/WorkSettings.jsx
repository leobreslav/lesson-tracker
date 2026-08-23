import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Hint from './Hint'
import { fetchGradingSystems } from './api'

/**
 * Мелкие поля работы: окно времени, попытки, показ отметки, признак
 * итоговой, система оценивания.
 *
 * **Стоят они отдельно от содержания, и это просьба заказчика, а не
 * раскладка ради раскладки.** Главное в работе — задание, которое прочтёт
 * класс, и задачи, которые он решит; всё перечисленное выше настраивают
 * один раз и потом не трогают. Пока они лежали вперемешку в одной форме,
 * задание оказывалось третьим полем сверху и делило экран с четырьмя
 * флажками.
 *
 * Поэтому на странице работы они уехали за кнопку «Настройки», а на
 * странице сами по себе не показываются вовсе. Форма заведения работы
 * держит их по-прежнему рядом: там их и заполняют — даты обязательны, без
 * них работы не завести.
 *
 * Компонент правит **чужое** состояние (`form`/`setForm`), а не своё, и это
 * намеренно: у обоих мест форма одна на всю работу, и второй источник
 * правды для пяти полей разошёлся бы с первым в первую же правку.
 */
export default function WorkSettings({ form, setForm, busy = false }) {
  const { t } = useTranslation()
  const [systems, setSystems] = useState([])

  /* Список систем школы: показываются только разрешённые — сервер их и не
     отдаёт другими, а форма не должна предлагать то, чего он не примет. */
  useEffect(() => {
    let alive = true
    fetchGradingSystems()
      .then((answer) => alive && setSystems(answer.systems.filter((one) => one.is_allowed)))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  const change = (field) => (event) => {
    const value =
      event.target.type === 'checkbox' ? event.target.checked : event.target.value
    setForm((current) => ({ ...current, [field]: value }))
  }

  return (
    <>
    <div className="row">
      <label className="field-with-hint">
        {t('works.opensAt')}
        <input
          type="datetime-local"
          value={form.opens_at}
          onChange={change('opens_at')}
        />
      </label>
      <label className="field-with-hint">
        {t('works.closesAt')}
        <input
          type="datetime-local"
          value={form.closes_at}
          onChange={change('closes_at')}
        />
      </label>
    </div>
    {/* Окно решает не «видно ли работу», а «принимаются ли решения», и
        это две разные вещи. Строка обещала первое — «ученик видит работу
        только пока окно открыто», — а на деле после закрытия у него
        остаётся всё: условия, свои ответы, баллы и переписка с учителем
        по задаче (треды окна не знают вовсе, право там по участию).
        Пропадает ровно одно — возможность прислать новое решение */}
    <Hint short={t('works.windowHint')} more={t('works.windowHintMore')} />

    {/* Система оценивания — решение учителя, на каждой работе своё:
        маленькая проверочная по пятибалльной рядом с контрольной по MYP
        это обычное дело. Администратор только ограничивает список. */}
    <label className="field">
      <span>{t('grading.system')}</span>
      <select
        value={form.grading_system ?? ''}
        onChange={(event) =>
          setForm({
            ...form,
            grading_system: event.target.value ? Number(event.target.value) : null,
          })
        }
      >
        <option value="">{t('grading.noSystem')}</option>
        {systems.map((system) => (
          <option key={system.id} value={system.id}>
            {system.name}
          </option>
        ))}
      </select>
    </label>
    {/* пояснение нужно самому первому пункту списка: «Только баллы, без
        отметки» — это отказ от системы, и по подписи не видно, что при
        этом остаётся.

        Развёрнутого под «?» здесь больше нет, и снято оно по просьбе:
        оно пересказывало устройство порогов, то есть отвечало на вопрос,
        которого в этой форме никто не задаёт, — пороги задаёт школа в
        своём справочнике. А главное, что про них стоило бы сказать, в
        форме про работу не помещается вовсе: **итог ставит учитель**.
        Что бы система ни вывела из баллов, его отметка сильнее, и живёт
        это правило там, где отметку и ставят, — в окне работы ученика */}
    <p className="hint">{t('grading.systemHint')}</p>

    {/* формативную оценивают как придётся, и в итог она не идёт */}
    <label className="checkbox">
      <input
        type="checkbox"
        checked={form.is_summative}
        onChange={change('is_summative')}
      />
      {t('works.summative')}
    </label>
    <p className="hint">{t('works.summativeHint')}</p>

    {/* попытки — про работу целиком, а не про отдельный вопрос: чекбокса
        «на бумаге» тут больше нет, и прятать эту строку стало не по чему.
        Работа, все ячейки которой пишут на бумаге, попыток не тратит, и
        число в них ничего не портит.

        Ряд по центру (`middle`), а не по низу: умолчание `flex-end`
        верно для ряда полей с подписями сверху, а здесь рядом стоят
        голый чекбокс ростом со строку и поле ростом с контрол — по
        нижнему краю подпись прибивало к донышку поля, и она читалась
        не как заголовок этого числа, а как что-то лежащее под ним */}
    <div className="row middle">
      <label className="checkbox">
        <input
          type="checkbox"
          checked={form.limited}
          onChange={change('limited')}
        />
        {t('works.limited')}
      </label>
      {form.limited && (
        <input
          type="number"
          min={1}
          max={20}
          value={form.attempts}
          aria-label={t('works.attempts')}
          onChange={change('attempts')}
        />
      )}
    </div>
    {/* «Один: ученик отправляет…» читалось как начало фразы, а не как
        пример: число в поле и число в тексте связывались не сразу.
        Теперь оба случая названы одинаково — «Стоит 1 — …», «Стоит 3 — …» */}
    <Hint short={t('works.attemptsHint')} more={t('works.attemptsHintMore')} />

    {/* «отметка» — слово из школьного обихода, и в форме оно ничего не
        называет. Скрывает флажок не «верно/неверно», а **баллы**: балл за
        каждую задачу, итоговую отметку за работу и комментарий учителя —
        всё разом (`show_result` у модели, `services.mark_for`). Первая
        версия подсказки говорила про вердикт, и это осталось от времён,
        когда вердикт был галочкой; баллом он стал давно */}
    <label className="checkbox">
      <input
        type="checkbox"
        checked={form.show_result}
        onChange={change('show_result')}
      />
      {t('works.showResult')}
    </label>
    <Hint
      short={t('works.showResultHint')}
      more={t('works.showResultHintMore')}
    />
    </>
  )
}
