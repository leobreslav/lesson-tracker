import { useTranslation } from 'react-i18next'

import { toggle } from './basket'

/**
 * «Отложить задачу» — одна кнопка, три экрана.
 *
 * Отмеченная остаётся отмеченной на всех: набор общий, а экраны — просто
 * разные способы до задачи добраться.
 */
export default function Pick({ id, picked, onChange }) {
  const { t } = useTranslation()
  const taken = picked.includes(id)

  return (
    <button
      type="button"
      className={taken ? 'pick taken' : 'pick'}
      title={taken ? t('bank.basket.drop') : t('bank.basket.take')}
      aria-label={taken ? t('bank.basket.drop') : t('bank.basket.take')}
      onClick={() => onChange(toggle(id))}
    >
      {taken ? '✓' : '+'}
    </button>
  )
}
