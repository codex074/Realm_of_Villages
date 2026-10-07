// Center view: the walled town zoomed in (slots 19-40).

import { renderScenePage } from './hud.js';

// Render the center page into el.
export async function render(el, ctx) {
  return renderScenePage(el, ctx, 'town');
}
