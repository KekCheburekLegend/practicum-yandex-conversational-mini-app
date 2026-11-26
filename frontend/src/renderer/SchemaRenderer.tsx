import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { inspectSchema, type Inspection, type Node, type UISchema } from './schema';
import styles from './renderer.module.css';

export type UIAction = { app_id: string; action: string; payload: Record<string, string> };
type Props = { schema: unknown; onAction: (action: UIAction) => void; onInspect?: (inspection: Inspection) => void };
type PrimitiveProps = { node: Node; children?: ReactNode; emit: (action: string, payload: Record<string, string>) => void };

const registry = {
  text: ({ node }: PrimitiveProps) => node.component_type === 'text' && <p>{node.props.text}</p>,
  card: ({ node, children }: PrimitiveProps) => node.component_type === 'card' &&
    <section className={styles.card}><h3>{node.props.title}</h3>{children}</section>,
  table: ({ node }: PrimitiveProps) => node.component_type === 'table' &&
    <div className={styles.table}><table><thead><tr>{node.props.columns.map((column, i) => <th key={i}>{column}</th>)}</tr></thead>
      <tbody>{node.props.rows.map((row, i) => <tr key={i}>{node.props.columns.map((_, j) => <td key={j}>{row[j] ?? ''}</td>)}</tr>)}</tbody></table></div>,
  chart: ({ node }: PrimitiveProps) => node.component_type === 'chart' && <figure className={styles.chart}>
    <figcaption>{node.props.title}</figcaption>{node.props.values.map((item, i) => <div key={i}>
      <span>{item.label}</span><meter min={0} max={Math.max(1, ...node.props.values.map(entry => entry.value))} value={item.value} />
      <span>{item.value}</span></div>)}</figure>,
  filter: ({ node, emit }: PrimitiveProps) => node.component_type === 'filter' && <label className={styles.field}>
    {node.props.label}<select defaultValue="" onChange={event => emit(node.props.action, { value: event.target.value })}>
      <option value="" disabled>Выберите значение</option>{node.props.options.map((option, i) => <option key={i}>{option}</option>)}
    </select></label>,
  form: ({ node, children, emit }: PrimitiveProps) => node.component_type === 'form' &&
    <section role="group" aria-label={node.props.label} className={styles.card}>{children}
      <button type="button" onClick={() => emit(node.props.action, {})}>{node.props.label}</button></section>,
  timeline: ({ node }: PrimitiveProps) => node.component_type === 'timeline' && <ol>
    {node.props.items.map((item, i) => <li key={i}><strong>{item.date}</strong> — {item.text}</li>)}</ol>,
  'source-link': ({ node }: PrimitiveProps) => node.component_type === 'source-link' &&
    <a href={node.props.href} target="_blank" rel="noopener noreferrer">{node.props.label} ↗</a>,
};

export function SchemaRenderer({ schema, onAction, onInspect }: Props) {
  const inspection = useMemo(() => inspectSchema(schema), [schema]);
  useEffect(() => { onInspect?.(inspection); }, [inspection, onInspect]);
  if (!inspection.valid) return <div role="alert">Не удалось открыть интерфейс. Ошибки схемы доступны в Inspect.</div>;
  const validated = schema as UISchema;
  const emit = (action: string, payload: Record<string, string>) => onAction({ app_id: validated.app_id, action, payload });
  function render(node: Node, index: number): ReactNode {
    const Component = registry[node.component_type];
    return <Component key={index} node={node} emit={emit}>{'nodes' in node && node.nodes.map(render)}</Component>;
  }
  return <div className={styles.renderer}>{validated.nodes.map(render)}</div>;
}

export function SchemaPlayground({ schema }: { schema: UISchema }) {
  const [inspection, setInspection] = useState<Inspection>({ valid: true, errors: [] });
  const [lastAction, setLastAction] = useState<UIAction | null>(null);
  const [input, setInput] = useState('');
  const [customSchema, setCustomSchema] = useState<unknown>(undefined);
  const [parseError, setParseError] = useState('');
  function apply(event: FormEvent) {
    event.preventDefault();
    try { setCustomSchema(JSON.parse(input)); setParseError(''); }
    catch { setParseError('Некорректный JSON'); }
  }
  return <>
    <SchemaRenderer schema={customSchema === undefined ? schema : customSchema} onInspect={setInspection} onAction={setLastAction} />
    <details className={styles.inspect}><summary>Inspect</summary>
      <p role="status">{inspection.valid ? 'Схема валидна' : 'Схема отклонена'}</p>
      <ul>{inspection.errors.map((error, i) => <li key={i}>{error.path} — {error.message}</li>)}</ul>
      {lastAction && <pre aria-label="Последнее действие">{JSON.stringify(lastAction, null, 2)}</pre>}
      <form onSubmit={apply}><label>Проверить UI-схему<textarea value={input} onChange={event => setInput(event.target.value)} maxLength={100000} rows={6} /></label>
        <button type="submit">Применить схему</button><button type="button" onClick={() => { setCustomSchema(undefined); setParseError(''); setLastAction(null); }}>Сбросить</button>
      </form>{parseError && <p role="alert">{parseError}</p>}
    </details>
  </>;
}

