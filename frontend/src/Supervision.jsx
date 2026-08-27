import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import CourseRow from './CourseRow'
import PlanTable from './PlanTable'
import { DiffBody } from './PlanDiff'
import Switch from './Switch'
import { shortDate } from './dates'
import { countBlocks, planRows } from './planLogic'
import { usePlanLayout } from './usePlanLayout'
import {
  approveReview,
  downloadPlan,
  fetchReview,
  fetchReviewDiff,
  fetchReviewSlots,
  returnReview,
} from './api'

/** Во что выгружают чужой план — те же два формата, что у автора. */
const FORMATS = ['xlsx', 'csv']

/**
 * Чужой план — на месте своего.
 *
 * Экраном методиста это было, и осталось им же: числа те же, что видит
 * учитель у себя, и считает их тот же `plans/progress.py` — два ответа на
 * один вопрос означали бы, что разговор про «отстаёшь» начинается со спора о
 * цифрах.
 *
 * **Читает его теперь вся школа**, а не один назначенный методист. Границей
 * права надзор никогда и не был: чужую программу открывают не только затем,
 * чтобы её подписать, — смежник сверяет, когда у соседей производная,
 * заменяющий смотрит, на чём остановились, новый учитель читает прошлогоднюю
 * параллель. Всем им отвечала библиотека, то есть **снимок**, который кто-то
 * догадался положить на полку; живой план соседа просто ни разу не
 * открывали. Второго экрана под это не завели: он показывал бы ровно то же
 * самое и разошёлся бы с этим в первую же правку.
 *
 * План виден **всегда**, а не только по присланному запросу: запрос — это
 * пометка в строке и подпись над планом («на утверждение не присылали»).
 *
 * **Показан он той же таблицей, что у автора** (`PlanTable` с `readOnly`), а
 * не своим списком названий. Список тут стоял и отвечал ровно на один вопрос
 * — «что написано»; приходят же с другими: когда у вас производная, на чём
 * вы остановились, успеваете ли до конца четверти. Отвечают на них даты,
 * номера недель, границы четвертей, черта «сегодня» и хвост незанятых часов
 * — то есть раскладка, которой в списке не было вовсе. Заодно список был
 * вторым ответом на вопрос «как выглядит план» и разошёлся бы с первым в
 * первую же правку таблицы.
 *
 * Разница между «править» и «смотреть» — это набор органов управления, а не
 * другая вёрстка, и живёт она одним пропом. Долги по записи сюда при этом не
 * приезжают: «не отметил двенадцать занятий» — про дисциплину заполнения, а
 * не про программу, и в чужом обзоре выглядит фактом, за которым никто не
 * приходил. Проведённые часы видны — за ними и пришли.
 *
 * **Выгрузка стоит здесь же.** Показать и не дать взять — не защита, а
 * неудобство: сорок строк, которые видно, но нельзя ни сверить столбцом к
 * столбцу, ни распечатать, всё равно перепишут руками и с ошибками. Файл
 * собирает тот же код, что у автора, и отдаёт по той же границе, по которой
 * этот план и открылся.
 *
 * Утвердить или вернуть — здесь же, и только у того, кому это можно
 * (`may_decide` с сервера). Возврат без замечания не принимается: учителю
 * нечего исправлять, а «верните как было» — не разговор.
 *
 * **Собирается экран из одного ответа, по одному id курса.** Строка
 * состояния приезжала пропом из списка надзора — то есть экран открывался
 * только тому, у кого этот курс в списке, а у рядового учителя списка нет
 * вовсе, и половина экрана осталась бы пустой.
 */
export default function Supervision({ courseId, busy, onError, onDone }) {
  const { t } = useTranslation()
  const [plan, setPlan] = useState(null)
  // сравнение с эталоном — второй взгляд на тот же присланный план, а не
  // второй экран: спрашивают тут «что изменилось», а не «что написано»
  const [diff, setDiff] = useState(null)
  const [comparing, setComparing] = useState(false)
  // версия эталона: null — последнее утверждение
  const [chosen, setChosen] = useState(null)
  const [returning, setReturning] = useState(false)
  const [comment, setComment] = useState('')
  // лента слотов чужого курса: даты, четверти и каникулы между уроками
  const [ribbon, setRibbon] = useState([])
  // «с датами» — уточнение к выгрузке, живёт столько же, сколько экран.
  // Коллеге оно нужнее, чем автору: чужой план и открывают ради раскладки,
  // а печатают перед разговором
  const [exportDates, setExportDates] = useState(false)
  // свёрнутые темы: это вид, а не правка, и читателю он нужен так же —
  // план на сорок строк листают, свернув то, что уже посмотрели
  const [collapsed, setCollapsed] = useState(() => new Set())

  const row = plan?.row ?? null
  const request = row?.review?.status === 'pending' ? row.review : null

  useEffect(() => {
    setPlan(null)
    setDiff(null)
    setComparing(false)
    setChosen(null)
    setReturning(false)
    setComment('')
    setRibbon([])
    setCollapsed(new Set())

    fetchReview(courseId).then(setPlan).catch(onError)

    /*
     * Лента дат — вторым запросом, и её отказ экран не роняет.
     *
     * План без дат читается: это программа, и «что написано» она отвечает
     * и так. А вот у курса, которому ещё не составили расписание, ленты
     * нет вовсе — состояние законное и частое (сентябрь ещё не собрали),
     * и падать на нём было бы неверно вдвойне.
     */
    fetchReviewSlots(courseId)
      .then((answer) => setRibbon(answer.slots))
      .catch(() => setRibbon([]))
  }, [courseId])

  useEffect(() => {
    // прежнее сравнение остаётся на экране, пока едет новая версия: иначе
    // смена версии на миг возвращала бы к списку плана
    fetchReviewDiff(courseId, chosen).then(setDiff).catch(onError)
  }, [courseId, chosen])

  /**
   * Раскладка — тем же хуком, каким её считает автор плана.
   *
   * Даты у строк, номера недель, границы четвертей, черта «сегодня» и
   * хвост незанятых часов. Своим расчётом «для читателя» это быть не
   * может: раскладка — правило (час со связью показывает свой урок,
   * отменённый час места не занимает), и два прохода разошлись бы молча —
   * ровно там, где двое смотрят в один план и спорят о датах.
   */
  const dated = ribbon.length > 0
  const layout = usePlanLayout(plan?.nodes, ribbon)
  const blocks = useMemo(
    () => countBlocks(planRows(plan?.nodes ?? [])),
    [plan],
  )

  const toggleSection = (id) =>
    setCollapsed((current) => {
      const next = new Set(current)
      if (!next.delete(id)) next.add(id)
      return next
    })

  const takeAway = async (format) => {
    try {
      await downloadPlan(courseId, format, {
        foreign: true,
        dates: exportDates,
      })
    } catch (err) {
      onError(err)
    }
  }

  /**
   * Что сказать про утверждение — ровно то же, что видит учитель.
   *
   * Ветки и фразы взяты у страницы плана (`plan.baseline.*`): один факт
   * должен читаться одинаково на обоих экранах, иначе разговор про план
   * начинается со сверки формулировок.
   */
  const approved = row?.baseline
  const waiting = row?.review
  const state = (() => {
    if (waiting?.status === 'pending') {
      return {
        kind: 'pending',
        text: t('plan.baseline.pending', { name: waiting.reviewer?.name ?? '' }),
      }
    }
    if (waiting?.status === 'returned') {
      return {
        kind: 'returned',
        text: `${t('plan.baseline.returned', {
          name: waiting.reviewer?.name ?? '',
        })} ${waiting.comment}`,
      }
    }
    if (approved) {
      return {
        kind: 'approved',
        text: t(
          approved.self_approved
            ? 'plan.baseline.approvedSelf'
            : 'plan.baseline.approved',
          {
            date: shortDate(approved.approved_at.slice(0, 10)),
            name: approved.reviewer?.name ?? '',
          },
        ),
      }
    }
    return null
  })()

  /**
   * Решили — и экран показывает решённое, не дожидаясь ничего.
   *
   * Состояние приезжало сюда пропом из списка надзора, и обновлял его
   * `onDone` снаружи, перечитывая список. Теперь экран собирает себя сам, и
   * тот же `onDone` его не касается — после «Утвердить» кнопки оставались
   * на месте, а заголовок по-прежнему говорил «Присланный план».
   *
   * Перечитывать при этом нечего: и утверждение, и возврат отвечают **тем
   * же** полным ответом экрана, что и открытие. Второй запрос следом
   * означал бы состояние между ними — то, за которое отвечать некому.
   */
  const decide = async (action) => {
    try {
      setPlan(await action())
      setReturning(false)
      setComment('')
      onDone()
    } catch (err) {
      onError(err)
    }
  }

  /*
   * Пока ответа нет, экрана нет: рисовать шапку из полупустых полей
   * незачем, а собирается она вся из одного запроса.
   */
  if (!row) return null

  return (
    <>
      <ul className="progress-list">
        <CourseRow
          row={row}
          open
          onToggle={() => {}}
          mark={
            /* одной ячейкой: в шапке сетка на четыре колонки, и две
               отдельные пометки разъехались бы по разным местам */
            <span className="whose">
              {/* курс без ведущего — нормальное состояние: нагрузку ещё не
                  раздали, и методисту это как раз видно */}
              {row.teacher?.name ?? t('reviews.noTeacher')}
              {request && <span className="badge waiting">{t('reviews.mark')}</span>}
            </span>
          }
        />
      </ul>

      {/*
        Состояние утверждения — теми же словами, что у автора плана.

        Плашкой оно было («эталон не утверждён», «+3 добавлено в план»), и
        это был второй способ сказать то, что учитель у себя читает строкой
        в шапке, а разбирает — в сравнении. Два вида одного факта
        расходятся молча: плашка считала переименование ничем, сравнение
        считает его правкой, и спорить об этом методист с учителем стали бы
        глядя каждый в свой экран. Поэтому строка тут одна и ключи у неё те
        же, что на странице плана, а «чем разошлось» отвечает тумблер
        «Сравнение» ниже — общий для обоих.

        Порядок веток тот же: запрос в работе важнее прошлой подписи.
      */}
      {state && <p className={`hint approval ${state.kind}`}>{state.text}</p>}

      {/* «На утверждение не присылали» сказано тому, кто утверждает: для
          него это состояние работы. Читателю со стороны эта строка сообщает
          про процедуру, в которой он не участвует, — то есть ни о чём */}
      {plan.may_decide && !row.review && !row.baseline && (
        <p className="hint">{t('reviews.nothingSent')}</p>
      )}

      {plan && (
        <section className="panel">
          <div className="panel-head spread">
            {/* «Присланный план» и «План курса» — разные вещи, и путать
                их нельзя: во втором случае методист смотрит рабочий
                черновик, за который автор ещё не отвечал */}
            <h3>
              {t(
                comparing
                  ? 'plan.diff.title'
                  : request
                    ? 'reviews.sentPlan'
                    : 'reviews.coursePlan',
              )}
            </h3>
            <span className="row">
              {/* сравнивать не с чем, пока план не утверждали ни разу:
                  первый запрос и есть точка отсчёта. Тумблер тот же, что у
                  автора плана: два вида, оба названы */}
              {diff?.baseline && (
                <Switch
                  label={t('plan.diff.switch')}
                  value={comparing}
                  onChange={setComparing}
                  options={[
                    { value: false, label: t('plan.diff.plan') },
                    { value: true, label: t('plan.diff.toggle') },
                  ]}
                />
              )}
              {/*
                Взять файлом — не только посмотреть.

                Показать и не дать взять — это не защита, а неудобство:
                сорок строк, которые видно, но нельзя ни сверить столбцом к
                столбцу, ни распечатать перед разговором, всё равно
                перепишут руками и с ошибками. Права выгрузка не расширяет
                ни на грамм — файл собирает тот же код, что у автора, и
                отдаёт по той же границе, по какой этот план и открылся.

                Формат называет саму кнопку: у выгрузки это вопрос «во
                что», а не настройка, которую держат включённой. Меню тут
                не заводим — в ряду и так тумблер, а двух кнопок меньше,
                чем меню с двумя пунктами.
              */}
              {/* «с датами» — то же уточнение, что у автора в меню, и здесь
                  оно нужнее: чужой план открывают ради раскладки, а
                  распечатывают перед разговором. Стоит перед кнопками,
                  потому что уточняет их обе */}
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={exportDates}
                  onChange={(event) => setExportDates(event.target.checked)}
                />
                {t('plan.exportWithDates')}
              </label>
              {FORMATS.map((name) => (
                <button
                  key={name}
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => takeAway(name)}
                >
                  {t('plan.exportAs', { format: name })}
                </button>
              ))}
            </span>
          </div>

          {/* план целиком — тот, что методист видит сейчас: правки после
              отправки ничего не отзывают, и утверждается увиденное */}
          {/*
            План целиком — **той же таблицей**, что у автора, только на
            чтение.

            Своим списком названий это было, и список отвечал ровно на один
            вопрос: «что написано». А приходят к соседу с другими — когда у
            вас производная, на чём вы остановились, успеваете ли до конца
            четверти, — и на них отвечают даты, недели, границы четвертей и
            хвост незанятых часов, то есть всё то, чего в списке не было.
            Заодно это был второй ответ на вопрос «как выглядит план»,
            который начал бы расходиться с первым в первую же правку
            таблицы.

            Долги по записи (прошедший час без записи) сюда не приезжают, и
            это то же решение, что вынуло их из строки состояния: «не
            отметил двенадцать занятий» — про дисциплину заполнения, а не
            про программу, и в чужом обзоре это поле выглядит фактом, за
            которым никто не приходил. Проведённые часы при этом видны:
            «на чём остановились» — как раз то, зачем сюда пришли.
          */}
          {comparing && diff ? (
            <DiffBody data={diff} onVersion={setChosen} />
          ) : (
            <PlanTable
              readOnly
              nodes={plan.nodes}
              layout={layout}
              blocks={blocks}
              dated={dated}
              busy={busy}
              collapsed={collapsed}
              editing={null}
              adding={null}
              actions={{ toggleSection }}
            />
          )}

          {/* Решают только то, что прислали, и только те, кому это можно:
              у курса без запроса кнопки обещали бы действие, которого
              сервер не сделает, а у читателя со стороны — действие, на
              которое он получит отказ. Право приезжает ответом, а не
              выводится из роли: правило сложнее роли — методист **этого
              курса**. */}
          {plan.may_decide &&
            request &&
            (returning ? (
            <>
              <label className="field-with-hint">
                <span>{t('reviews.comment')}</span>
                <textarea
                  autoFocus
                  rows={3}
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                />
              </label>
              <div className="actions">
                <button
                  type="button"
                  disabled={busy || !comment.trim()}
                  onClick={() => decide(() => returnReview(courseId, comment.trim()))}
                >
                  {t('reviews.sendBack')}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setReturning(false)}
                >
                  {t('common.cancel')}
                </button>
              </div>
            </>
          ) : (
            <div className="actions wrap">
              <button
                type="button"
                disabled={busy}
                onClick={() => decide(() => approveReview(courseId))}
              >
                {t('reviews.approve')}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setReturning(true)}
              >
                {t('reviews.return')}
              </button>
            </div>
            ))}
        </section>
      )}
    </>
  )
}
