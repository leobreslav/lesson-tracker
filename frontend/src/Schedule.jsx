import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import Agenda from './Agenda'
import SchoolSchedule from './SchoolSchedule'
import Switch from './Switch'

/**
 * Расписание — одна страница, два вида.
 *
 * Их было два экрана: «Моё расписание» и «Расписание школы». Живут они на
 * одних данных — с тех пор как `MasterSlot` не стало, школьное расписание
 * это все расписания курсов, — и различаются ровно двумя вещами: какие
 * курсы показаны и что написано в клетке. А ходить между ними приходилось
 * через раздел «Школа»: завуч, глядя на свою неделю, не мог поставить час
 * чужому курсу, не уйдя со страницы и не найдя её заново.
 *
 * Поэтому вид переключается **на месте**, тумблером в шапке, а входов
 * по-прежнему два — из бара и из раздела «Школа». Оба ведут сюда; старый
 * адрес `/school/schedule` остался и приводит на этот же экран в школьном
 * виде.
 *
 * Вид живёт в адресе (`?view=school`), а не в состоянии: тогда «назад»
 * возвращает в тот вид, из которого ушли, а ссылку на школьный вид можно
 * дать словами.
 *
 * Тумблер видит только администратор школы. Учителю чужие часы править
 * нечем (`IsCourseTeacherOrSchoolAdmin` пускает его в свои курсы, и они у
 * него и так на экране), а видеть их он может там же, где и раньше.
 */
export default function Schedule({ user, onLoggedOut }) {
  const { t } = useTranslation()
  const [search, setSearch] = useSearchParams()

  const school = user?.is_school_admin && search.get('view') === 'school'

  const views = user?.is_school_admin ? (
    <Switch
      label={t('agenda.views.label')}
      value={school ? 'school' : 'mine'}
      options={[
        { value: 'mine', label: t('agenda.views.mine') },
        { value: 'school', label: t('agenda.views.school') },
      ]}
      onChange={(value) => {
        // replace, а не push: тумблер — не шаг в истории, иначе «назад»
        // после трёх нажатий возвращало бы по одному виду за раз
        const next = new URLSearchParams(search)
        if (value === 'school') next.set('view', 'school')
        else next.delete('view')
        setSearch(next, { replace: true })
      }}
    />
  ) : null

  return school ? (
    <SchoolSchedule views={views} onLoggedOut={onLoggedOut} />
  ) : (
    <Agenda views={views} onLoggedOut={onLoggedOut} />
  )
}
