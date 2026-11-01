import { useSyncExternalStore } from 'react'

export type Lang = 'ru' | 'en'

const dict = {
  en: {
    'status.online': 'AI READY',
    'hero.eyebrow': 'AI DOCUMENT INTELLIGENCE',
    'hero.title1': 'Ask your',
    'hero.title2': 'documents.',
    'hero.text': 'Upload documents in English or Russian, find the one you need, and get answers to key questions',
    'search.label': 'ASK AI',
    'search.placeholder': 'Ask a question about your documents',
    'search.button': 'Ask AI',
    'search.loading': 'Searching...',
    'search.hintsLabel': 'For example:',
    'hint1.label': 'data by year',
    'hint1.q': 'Find data for 2023',
    'hint2.label': 'financial indicators',
    'hint2.q': 'What revenue or profit is indicated?',
    'hint3.label': 'market shares',
    'hint3.q': 'What market shares are indicated for companies?',
    'footer.private': 'PRIVATE DOCUMENT SEARCH',
    'footer.grounded': 'GROUNDED AI',
    'sidebar.brand': 'AI DOCUMENT AGENT',
    'sidebar.documents': 'DOCUMENTS',
    'sidebar.add': 'Add documents',
    'sidebar.empty': 'Your documents will appear here',
    'sidebar.online': 'AI system online',
    'sidebar.indexed': 'indexed',
    'sidebar.clear': 'Delete my data',
    'sidebar.delete': 'Delete',
    'status.ready': 'Indexed',
    'status.processing': 'Processing',
    'status.queued': 'Queued',
    'status.failed': 'Failed',
    'answer.close': 'Close',
    'answer.you': 'YOU',
    'answer.ai': 'AI ANSWER',
    'answer.sources': 'FOUND IN THESE DOCUMENTS',
    'answer.verified': 'Quote verified in the document',
    'answer.unverified': 'Excerpt from the document (the exact quote could not be verified)',
    'progress.title': 'Indexing documents',
    'progress.text': 'AI analyzes the content and creates a search index',
    'progress.hide': 'Continue in background',
    'progress.files': 'Documents ready:',
    'notice.duplicates': 'Skipped duplicates:',
    'err.generic': 'Request failed',
    'err.network': 'Cannot reach the server. Check your connection and try again.',
    'err.rate': 'Too many requests. Please wait a moment and try again.',
    'err.busy': 'The service is busy. Please try again shortly.',
    'err.status': 'Request error',
    'step.analyze': 'Analyzing the question',
    'step.rewrite': 'Preparing search queries',
    'step.retrieve': 'Searching documents',
    'step.rerank': 'Ranking passages',
    'step.reformulate': 'Trying other wording',
    'step.generate': 'Writing the answer',
    'step.verify': 'Checking citations',
    'step.sql_plan': 'Planning a calculation',
    'step.sql_exec': 'Running the calculation',
    'step.sql_answer': 'Explaining the result',
    'step.sql_fallback': 'Falling back to text search',
    'step.no_docs': 'Checking documents',
    'step.not_found': 'Wrapping up',
    'answer.calculation': 'CALCULATION',
    'answer.rows': 'rows',
    'answer.truncated': 'result truncated',
    'answer.how': 'HOW THIS WAS FOUND',
    'answer.rewritten': 'Search query:',
    'answer.table': 'Table',
    'progress.stage.parsing': 'Reading the document',
    'progress.stage.ocr': 'Recognizing scanned text (OCR)',
    'progress.stage.indexing': 'Building the search index',
    'unlock.title': 'Access code',
    'unlock.text': 'This deployment is protected. Enter the access code to continue.',
    'unlock.placeholder': 'Access code',
    'unlock.button': 'Continue',
    'unlock.wrong': 'Wrong access code.',
  },
  ru: {
    'status.online': 'AI ГОТОВ',
    'hero.eyebrow': 'AI-АНАЛИЗ ДОКУМЕНТОВ',
    'hero.title1': 'Найдите',
    'hero.title2': 'документы',
    'hero.text': 'Загружайте документы на русском или английском, находите нужный и получайте ответы на ключевые вопросы',
    'search.label': 'СПРОСИТЬ AI',
    'search.placeholder': 'Задайте вопрос по вашим документам',
    'search.button': 'Спросить',
    'search.loading': 'Ищу...',
    'search.hintsLabel': 'Например:',
    'hint1.label': 'данные за год',
    'hint1.q': 'Найди данные за 2023 год',
    'hint2.label': 'финансовые показатели',
    'hint2.q': 'Какая указана выручка или прибыль?',
    'hint3.label': 'доли рынка',
    'hint3.q': 'Какие доли рынка указаны для компаний?',
    'footer.private': 'ПРИВАТНЫЙ ПОИСК ПО ДОКУМЕНТАМ',
    'footer.grounded': 'ОТВЕТЫ ПО ИСТОЧНИКАМ',
    'sidebar.brand': 'AI-АГЕНТ ДОКУМЕНТОВ',
    'sidebar.documents': 'ДОКУМЕНТЫ',
    'sidebar.add': 'Добавить документы',
    'sidebar.empty': 'Здесь появятся ваши документы',
    'sidebar.online': 'AI-система работает',
    'sidebar.indexed': 'проиндексировано',
    'sidebar.clear': 'Удалить мои данные',
    'sidebar.delete': 'Удалить',
    'status.ready': 'Готов',
    'status.processing': 'Обработка',
    'status.queued': 'В очереди',
    'status.failed': 'Ошибка',
    'answer.close': 'Закрыть',
    'answer.you': 'ВЫ',
    'answer.ai': 'ОТВЕТ AI',
    'answer.sources': 'ДАННЫЕ НАЙДЕНЫ В ЭТИХ ДОКУМЕНТАХ',
    'answer.verified': 'Цитата подтверждена в документе',
    'answer.unverified': 'Фрагмент документа (точную цитату подтвердить не удалось)',
    'progress.title': 'Индексация документов',
    'progress.text': 'AI анализирует содержимое и строит поисковый индекс',
    'progress.hide': 'Продолжить в фоне',
    'progress.files': 'Готово документов:',
    'notice.duplicates': 'Пропущены дубликаты:',
    'err.generic': 'Не удалось выполнить запрос',
    'err.network': 'Нет связи с сервером. Проверьте соединение и повторите попытку.',
    'err.rate': 'Слишком много запросов. Подождите немного и повторите.',
    'err.busy': 'Сервис перегружен. Повторите попытку чуть позже.',
    'err.status': 'Ошибка запроса',
    'step.analyze': 'Анализирую вопрос',
    'step.rewrite': 'Готовлю поисковые запросы',
    'step.retrieve': 'Ищу по документам',
    'step.rerank': 'Ранжирую фрагменты',
    'step.reformulate': 'Пробую другие формулировки',
    'step.generate': 'Пишу ответ',
    'step.verify': 'Проверяю цитаты',
    'step.sql_plan': 'Планирую вычисление',
    'step.sql_exec': 'Выполняю вычисление',
    'step.sql_answer': 'Объясняю результат',
    'step.sql_fallback': 'Перехожу к текстовому поиску',
    'step.no_docs': 'Проверяю документы',
    'step.not_found': 'Завершаю',
    'answer.calculation': 'ВЫЧИСЛЕНИЕ',
    'answer.rows': 'строк',
    'answer.truncated': 'результат обрезан',
    'answer.how': 'КАК ЭТО БЫЛО НАЙДЕНО',
    'answer.rewritten': 'Поисковый запрос:',
    'answer.table': 'Таблица',
    'progress.stage.parsing': 'Читаю документ',
    'progress.stage.ocr': 'Распознаю отсканированный текст (OCR)',
    'progress.stage.indexing': 'Строю поисковый индекс',
    'unlock.title': 'Код доступа',
    'unlock.text': 'Этот сервис защищён. Введите код доступа, чтобы продолжить.',
    'unlock.placeholder': 'Код доступа',
    'unlock.button': 'Продолжить',
    'unlock.wrong': 'Неверный код доступа.',
  },
} as const

export type Key = keyof (typeof dict)['en']

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem('lang')
    if (saved === 'ru' || saved === 'en') return saved
  } catch {
    // storage unavailable (private mode) - fall through
  }
  return navigator.language?.toLowerCase().startsWith('ru') ? 'ru' : 'en'
}

let current: Lang = initialLang()
const listeners = new Set<() => void>()
document.documentElement.lang = current

export function getLang(): Lang {
  return current
}

export function setLang(lang: Lang): void {
  current = lang
  document.documentElement.lang = lang
  try {
    localStorage.setItem('lang', lang)
  } catch {
    // ignore
  }
  listeners.forEach((l) => l())
}

export function t(key: Key): string {
  return dict[current][key]
}

/** Re-renders the component when the language changes; returns { t, lang }. */
export function useI18n() {
  const lang = useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => current,
  )
  return { lang, t: (key: Key) => dict[lang][key] }
}
