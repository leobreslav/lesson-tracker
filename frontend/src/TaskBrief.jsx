import { useTranslation } from 'react-i18next'
import Markdown from './Markdown'

/**
 * Условие задачи и допустимые ответы — шапка обоих окон проверки.
 *
 * Учитель сверяется с эталоном глазами, а не с памятью: без него проверка
 * ячейки превращается в «а что тут вообще спрашивали». Один компонент на
 * оба окна, потому что вопрос в них один и тот же — «что проверяем».
 */
export default function TaskBrief({ task }) {
  const { t } = useTranslation()

  if (!task) return null

  return (
    <div className="task-brief">
      <div className="task-question">
        <Markdown text={task.question} />
      </div>
      <div className="row answers">
        {task.answers.length === 0 ? (
          <span className="hint">{t('works.task.noAnswers')}</span>
        ) : (
          <>
            <span className="hint">
              {t('table.expected', { count: task.answers.length })}
            </span>
            {task.answers.map((answer, index) => (
              <span className="tag answer-text" key={index}>
                {answer}
              </span>
            ))}
          </>
        )}
      </div>
    </div>
  )
}
