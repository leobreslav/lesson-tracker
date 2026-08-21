import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { fetchTags } from './api'
import { lastChoice, rememberChoice } from './remember'

const KEY = 'bank.subject'

/**
 * Предмет — самый глобальный фильтр банка.
 *
 * С него начинают («мне нужна алгебра»), и держаться он должен между
 * экранами и заходами: учитель математики не выбирает предмет заново каждый
 * раз, когда открывает поиск. Поэтому выбор живёт в `localStorage`, ключ один
 * на все экраны банка — как `lastChoice('course')` у курса.
 *
 * Технически предмет — обычный тег вида `subject`, и своего справочника у него
 * нет: второе хранилище предмета разошлось бы с разметкой на первой правке.
 */
export default function SubjectPicker({ value, onChange }) {
  const { t } = useTranslation()
  const [subjects, setSubjects] = useState([])

  useEffect(() => {
    fetchTags('subject')
      .then((answer) => setSubjects(answer.tags))
      .catch(() => setSubjects([]))
  }, [])

  // Предметов в словаре нет — выбирать не из чего, и полоса с пустым селектом
  // читалась бы как поломка.
  if (subjects.length === 0) return null

  return (
    <label className="field">
      <span>{t('bank.subject')}</span>
      <select
        value={value || ''}
        onChange={(event) => {
          const chosen = event.target.value ? Number(event.target.value) : null
          rememberChoice(KEY, chosen ?? '')
          onChange(chosen)
        }}
      >
        <option value="">{t('bank.anySubject')}</option>
        {subjects.map((tag) => (
          <option key={tag.id} value={tag.id}>
            {tag.name}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Что было выбрано в прошлый раз — читают все экраны банка. */
export const chosenSubject = () => lastChoice(KEY)
