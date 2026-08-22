import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import ru from './locales/ru.json'

export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'ru', label: 'Русский' },
]

export const DEFAULT_LANGUAGE = 'en'

const KNOWN = new Set(LANGUAGES.map((item) => item.code))

/**
 * Language before signing in: there is no profile yet to ask.
 *
 * navigator.language gives a full tag such as ru-RU, so only the base
 * language counts; anything unfamiliar falls back to English.
 */
export function browserLanguage(navigatorLanguages = navigator?.languages) {
  for (const tag of navigatorLanguages || []) {
    const base = String(tag).split('-')[0].toLowerCase()
    if (KNOWN.has(base)) return base
  }
  return DEFAULT_LANGUAGE
}

export function normalizeLanguage(code) {
  return KNOWN.has(code) ? code : DEFAULT_LANGUAGE
}

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, ru: { translation: ru } },
  lng: DEFAULT_LANGUAGE,
  fallbackLng: DEFAULT_LANGUAGE,
  // React escapes on its own; a second pass would mangle quotes and dashes
  interpolation: { escapeValue: false },
})

export default i18n
