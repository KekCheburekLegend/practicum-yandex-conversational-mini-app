import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { inspectSchema } from './schema';
import { demoSchema } from './demo';
import { SchemaRenderer } from './SchemaRenderer';

const valid = demoSchema('research', 'Research Board');
const render = (schema: unknown) => renderToStaticMarkup(<SchemaRenderer schema={schema} onAction={() => { throw new Error('Action during rendering'); }} />);

describe('Schema Renderer', () => {
  it('validates and renders all eight primitives including nested containers', () => {
    expect(inspectSchema(valid)).toEqual({ valid: true, errors: [] });
    const html = render(valid);
    for (const tag of ['section', 'p', 'table', 'figure', 'select', 'button', 'ol', 'a']) expect(html).toContain(`<${tag}`);
  });
  it.each([
    { ...valid, schema_version: '2.0' },
    { ...valid, app_id: undefined },
    { ...valid, nodes: [{ component_type: 'script', props: {} }] },
    { ...valid, nodes: [{ component_type: 'text', props: { text: 42 } }] },
    { ...valid, nodes: [{ component_type: 'text', props: { text: 'x', onClick: 'alert(1)' } }] },
    { ...valid, nodes: [{ component_type: 'source-link', props: { label: 'x', href: 'javascript:alert(1)' } }] },
    { ...valid, nodes: [{ component_type: 'source-link', props: { label: 'x', href: 'data:text/html,x' } }] },
    null,
  ])('rejects unsafe or invalid schema %# without crashing', schema => {
    expect(inspectSchema(schema).valid).toBe(false);
    expect(inspectSchema(schema).errors.length).toBeGreaterThan(0);
    expect(render(schema)).toContain('role="alert"');
  });
  it('escapes HTML content', () => {
    const html = render({ ...valid, nodes: [{ component_type: 'text', props: { text: '<script>alert(1)</script>' } }] });
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<script>');
  });
  it('bounds cyclic and deeply nested inputs', () => {
    const cyclic: Record<string, unknown> = {}; cyclic.self = cyclic;
    expect(inspectSchema(cyclic).valid).toBe(false);
  });
});
