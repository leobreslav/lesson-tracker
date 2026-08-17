import { useTranslation } from 'react-i18next'

/**
 * Справка о формате CSV — то, что раньше висело подписью под кнопками.
 *
 * Постоянно показывать её незачем: файл импортируют раз в год, а строка
 * съедала место под каждым планом и всё равно не отвечала на главный
 * вопрос — какой файл подойдёт. Поэтому образец, правила и различие
 * режимов лежат здесь, а раскрывает их кнопка «?» у заголовка карточки.
 *
 * Образец собирается из строк словаря, а не пишется в разметке: шапка
 * должна совпадать с той, которую требует разбор, и на двух языках она
 * одинаковая — это часть формата, а не перевод.
 */

// столбцы те же и в книге: у CSV они через запятую, в xlsx — три ячейки
const SAMPLE = [
  'id,Тема,Урок',
  '412,Тригонометрия,Синус суммы',
  '413,Тригонометрия,Косинус суммы',
  ',Тригонометрия,Новый урок',
  '414,,Повторение',
]

const RULES = ['oneRow', 'repeat', 'emptyTheme', 'emptyId']
const MODES = ['sync', 'append', 'replace']

export default function PlanCsvHelp() {
  const { t } = useTranslation()

  return (
    <div className="csv-help">
      <p>{t('plan.csvHelp.formats')}</p>

      <pre className="csv-sample">{SAMPLE.join('\n')}</pre>

      <ul className="csv-rules">
        {RULES.map((rule) => (
          <li key={rule}>{t(`plan.csvHelp.rules.${rule}`)}</li>
        ))}
      </ul>

      <p className="hint">{t('plan.csvHelp.keeps')}</p>

      <dl className="csv-modes-help">
        {MODES.map((mode) => (
          <div key={mode}>
            <dt>{t(`csv.mode.${mode}`)}</dt>
            <dd>{t(`plan.csvHelp.modes.${mode}`)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
