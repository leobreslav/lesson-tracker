import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import Agenda from './Agenda'
import SchoolSchedule from './SchoolSchedule'
import Switch from './Switch'
import { AXES } from './dayAxis'

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
 *
 * **Сколько показано — тоже адрес** (`?span=day`), и по той же причине.
 * Расписание школы умеет два размаха: неделя всех курсов и один день, где
 * курсы развёрнуты по столбцам. Ссылкой «вот вторник, смотри» пользуются
 * ровно так же, как ссылкой на школьный вид, а «назад» после ухода в
 * занятие обязано вернуть тот размах, из которого ушли.
 */
export default function Schedule({ user, onLoggedOut }) {
  const { t } = useTranslation()
  const [search, setSearch] = useSearchParams()

  const school = user?.is_school_admin && search.get('view') === 'school'
  const span = search.get('span') === 'day' ? 'day' : 'week'
  // ось столбцов дневного вида — там же, в адресе: «вот вторник по
  // кабинетам» посылают ссылкой ровно так же, как сам вторник
  const axis = AXES.includes(search.get('by')) ? search.get('by') : AXES[0]

  // `replace` — тем же доводом, что у вида: размах не шаг в истории
  const setParam = (key, value, fallback) => {
    const next = new URLSearchParams(search)
    if (value === fallback) next.delete(key)
    else next.set(key, value)
    setSearch(next, { replace: true })
  }

  const views = user?.is_school_admin ? (
    <Switch
      label={t('agenda.views.label')}
      value={school ? 'school' : 'mine'}
      options={[
        { value: 'mine', label: t('agenda.views.mine') },
        { value: 'school', label: t('agenda.views.school') },
      ]}
      onChange={(value) => setParam('view', value, 'mine')}
    />
  ) : null

  return school ? (
    <SchoolSchedule
      views={views}
      span={span}
      onSpan={(value) => setParam('span', value, 'week')}
      axis={axis}
      onAxis={(value) => setParam('by', value, AXES[0])}
      onLoggedOut={onLoggedOut}
    />
  ) : (
    <Agenda views={views} onLoggedOut={onLoggedOut} />
  )
}
