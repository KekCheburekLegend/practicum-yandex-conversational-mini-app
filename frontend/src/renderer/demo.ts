import type { UISchema } from './schema';

export function demoSchema(appId: string, title: string): UISchema {
  return {
    schema_version: '1.0', app_id: appId,
    nodes: [
      { component_type: 'card', props: { title }, nodes: [
        { component_type: 'text', props: { text: 'Пример UI-схемы. Данные демонстрационные.' } },
        { component_type: 'source-link', props: { label: 'Репозиторий проекта', href: 'https://github.com/KekCheburekLegend/practicum-yandex-conversational-mini-app' } },
      ] },
      { component_type: 'table', props: { columns: ['Сценарий', 'Статус'], rows: [['Проверка схемы', 'Готово'], ['Подключение runtime', 'Ожидается']] } },
      { component_type: 'chart', props: { title: 'Пример диаграммы', values: [{ label: 'А', value: 3 }, { label: 'Б', value: 5 }] } },
      { component_type: 'form', props: { label: 'Вернуть итог', action: 'submit' }, nodes: [
        { component_type: 'filter', props: { label: 'Статус', options: ['Все', 'Готово'], action: 'filter' } },
      ] },
      { component_type: 'timeline', props: { items: [{ date: 'Этап 1', text: 'Запрос из чата' }, { date: 'Этап 2', text: 'Проверка и отображение схемы' }] } },
    ],
  };
}
