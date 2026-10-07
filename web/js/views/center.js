// Center view: the walled town zoomed in (slots 19-40), drawn by the scene module.

import { h, clear } from '../dom.js';
import { queuePanel } from './slotpanel.js';
import { sceneFrame } from './scene.js';

const HEADING = 'ใจกลางหมู่บ้าน';

// Render the center page into el.
export async function render(el, ctx) {
  clear(el);
  el.append(
    h('h1', { class: 'village-name' }, HEADING),
    sceneFrame(el, ctx, 'town'),
    queuePanel(ctx),
  );
}
