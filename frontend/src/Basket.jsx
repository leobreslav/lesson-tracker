import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import AssembleDialog from './AssembleDialog'
import CopyToShelf from './CopyToShelf'
import { clear, taken } from './basket'

/**
 * Полоса отобранного: сколько набрано и что с этим сделать.
 *
 * Стоит она под шапкой на всех трёх экранах банка — там, где задачи и
 * отбирают, — и появляется, только когда набрано хоть что-то: пустая полоса
 * «отобрано 0» это строка, объясняющая отсутствие.
 *
 * Число здесь главное: набор живёт между экранами и переживает перезагрузку,
 * и человек должен видеть, что он всё ещё что-то держит в руках.
 */
export default function Basket({ picked, onChange }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [assembling, setAssembling] = useState(false)
  const [shelving, setShelving] = useState(false)

  if (!picked.length) return null

  return (
    <p className="basket">
      <b>{t('bank.basket.count', { count: picked.length })}</b>
      <button type="button" onClick={() => setAssembling(true)}>
        {t('bank.basket.assemble')}
      </button>
      {/* второй адрес у того же отбора: работа и книга — два места, где
          условие лежит, и класть в них надо одинаково легко */}
      <button type="button" className="secondary" onClick={() => setShelving(true)}>
        {t('bank.basket.toBook')}
      </button>
      <button
        type="button"
        className="link"
        onClick={() => {
          clear()
          onChange(taken())
        }}
      >
        {t('bank.basket.clear')}
      </button>

      {shelving && (
        <CopyToShelf
          problems={picked}
          onClose={() => setShelving(false)}
          onDone={() => {
            clear()
            onChange(taken())
            setShelving(false)
          }}
        />
      )}

      {assembling && (
        <AssembleDialog
          problems={picked}
          onClose={() => setAssembling(false)}
          onDone={(work) => {
            // Набор отдан работе — держать его дальше значит предлагать
            // задать то же самое второй раз.
            clear()
            onChange(taken())
            setAssembling(false)
            navigate(`/works/${work.id}`)
          }}
        />
      )}
    </p>
  )
}
