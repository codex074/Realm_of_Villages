// Minimal DOM builder: safe element creation without innerHTML.

const BOOLEAN_ATTRS = new Set([
  'disabled',
  'hidden',
  'checked',
  'selected',
  'readonly',
  'required',
  'multiple',
  'autofocus',
  'open',
]);

function appendChildren(el, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) appendChildren(el, child);
    else if (typeof child === 'string' || typeof child === 'number') el.append(child);
    else if (child instanceof Node) el.append(child);
  }
}

// Build an element from a tag, an attrs object and nested children.
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined) continue;
    if (key === 'class') el.className = value;
    else if (key === 'style' && typeof value === 'object') Object.assign(el.style, value);
    else if (key === 'dataset' && typeof value === 'object') Object.assign(el.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function')
      el.addEventListener(key.slice(2), value);
    else if (BOOLEAN_ATTRS.has(key)) el[key] = !!value;
    else el.setAttribute(key, value);
  }
  appendChildren(el, children);
  return el;
}

// Remove all children of el.
export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

const SVG_NS = 'http://www.w3.org/2000/svg';

// Hand-drawn sprite icon (web/img/icons.svg): icon('wood') -> <svg class="ico"><use .../></svg>.
export function icon(name, cls = 'ico') {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', cls);
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', `img/icons.svg#i-${name}`);
  svg.append(use);
  return svg;
}
