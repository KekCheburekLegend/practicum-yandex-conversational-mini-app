import Ajv from 'ajv';

export type Node =
  | { component_type: 'text'; props: { text: string } }
  | { component_type: 'card'; props: { title: string }; nodes: Node[] }
  | { component_type: 'table'; props: { columns: string[]; rows: string[][] } }
  | { component_type: 'chart'; props: { title: string; values: { label: string; value: number }[] } }
  | { component_type: 'filter'; props: { label: string; options: string[]; action: string } }
  | { component_type: 'form'; props: { label: string; action: string }; nodes: Node[] }
  | { component_type: 'timeline'; props: { items: { date: string; text: string }[] } }
  | { component_type: 'source-link'; props: { label: string; href: string } };
export type UISchema = { schema_version: '1.0'; app_id: string; nodes: Node[] };
export type Inspection = { valid: boolean; errors: { path: string; message: string }[] };
const text = { type: 'string', maxLength: 10000 };
const identifier = { type: 'string', minLength: 1, maxLength: 100, pattern: '^[a-zA-Z0-9_.-]+$' };
const stringList = { type: 'array', maxItems: 100, items: text };
const children = { type: 'array', maxItems: 100, items: { $ref: '#/$defs/node' } };
const primitives = {
  text: { text },
  card: { title: text },
  table: { columns: { ...stringList, minItems: 1 }, rows: { type: 'array', maxItems: 1000, items: stringList } },
  chart: { title: text, values: { type: 'array', maxItems: 100, items: {
    type: 'object', additionalProperties: false, required: ['label', 'value'],
    properties: { label: text, value: { type: 'number', minimum: 0, maximum: 1000000000 } },
  } } },
  filter: { label: text, options: { ...stringList, minItems: 1 }, action: identifier },
  form: { label: text, action: identifier },
  timeline: { items: { type: 'array', maxItems: 100, items: {
    type: 'object', additionalProperties: false, required: ['date', 'text'], properties: { date: text, text },
  } } },
  'source-link': { label: text, href: { type: 'string', maxLength: 2000, format: 'safe-url' } },
};
const contract = {
  type: 'object', additionalProperties: false,
  required: ['schema_version', 'app_id', 'nodes'],
  properties: { schema_version: { const: '1.0' }, app_id: identifier, nodes: children },
  $defs: { node: { oneOf: Object.entries(primitives).map(([name, properties]) => {
    const container = name === 'card' || name === 'form';
    return {
      type: 'object', additionalProperties: false,
      required: container ? ['component_type', 'props', 'nodes'] : ['component_type', 'props'],
      properties: {
        component_type: { const: name },
        props: { type: 'object', additionalProperties: false, required: Object.keys(properties), properties },
        ...(container ? { nodes: children } : {}),
      },
    };
  }) } },
};
const ajv = new Ajv({ strict: true, allErrors: false });
ajv.addFormat('safe-url', (value: string) => {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password;
  } catch { return false; }
});
const validate = ajv.compile<UISchema>(contract);

// Bound traversal before Ajv recursion, including cyclic values supplied by callers.
function withinLimits(value: unknown, depth = 0, budget = { remaining: 10000 }): boolean {
  if (depth > 32 || --budget.remaining < 0) return false;
  if (typeof value === 'string') return value.length <= 10000;
  if (value && typeof value === 'object') {
    return Object.values(value).every(child => withinLimits(child, depth + 1, budget));
  }
  return true;
}

export function inspectSchema(value: unknown): Inspection {
  if (!withinLimits(value)) return { valid: false, errors: [{ path: '/', message: 'Превышен размер или глубина схемы' }] };
  if (validate(value)) return { valid: true, errors: [] };
  return { valid: false, errors: (validate.errors ?? []).map(error => ({
    path: error.instancePath || '/', message: error.message ?? 'Невалидная схема',
  })) };
}
