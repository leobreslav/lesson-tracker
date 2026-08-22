/**
 * Отобранные задачи — то, из чего потом собирается работа.
 *
 * Живёт в `localStorage`, а не в состоянии страницы, по простой причине:
 * набирают задачи **на трёх экранах** — в поиске, в книге и в теме, — и
 * между ними ходят. Набор, исчезающий при переходе, означал бы, что собрать
 * работу можно только из одного источника, а так не бывает: две задачи из
 * учебника, одна из своего листочка и одна найденная поиском.
 *
 * Порядок — порядок отбора, и он значимый: учитель ставит задачи по
 * возрастанию сложности, а множество этот порядок теряет. Поэтому список, а
 * не `Set`, и повторный отбор той же задачи её не двигает.
 */

const KEY = 'bank.basket'

export function taken() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(saved) ? saved.filter((id) => Number.isInteger(id)) : []
  } catch {
    return []
  }
}

export function take(id) {
  const now = taken()
  return save(now.includes(id) ? now : [...now, id])
}

export function drop(id) {
  return save(taken().filter((one) => one !== id))
}

export function toggle(id) {
  return taken().includes(id) ? drop(id) : take(id)
}

export function clear() {
  return save([])
}

function save(list) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list))
  } catch {
    // приватный режим — набор живёт до перезагрузки, и это лучше отказа
  }
  return list
}
