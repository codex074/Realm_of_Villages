// Village view: the whole illustrated village (fields + walled town) fitted to the screen.

import { renderScenePage } from './hud.js';

// Render the village page into el.
export async function render(el, ctx) {
  return renderScenePage(el, ctx, 'all');
}
