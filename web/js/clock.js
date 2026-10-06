// Game clock: keeps an offset between server game time and local wall clock.

let offsetMs = 0;

// Set the offset from a server-provided game_now ISO timestamp.
export function syncClock(gameNowIso) {
  const server = Date.parse(gameNowIso);
  if (!Number.isNaN(server)) offsetMs = server - Date.now();
}

// Current game time as a local Date.
export function gameNow() {
  return new Date(Date.now() + offsetMs);
}

// Remaining milliseconds until the given game-time ISO timestamp.
export function remainingMs(iso) {
  const target = Date.parse(iso);
  if (Number.isNaN(target)) return 0;
  return Math.max(0, target - gameNow().getTime());
}

// Remaining time until the given game-time ISO timestamp as 'H:MM:SS'.
export function countdown(iso) {
  let total = Math.floor(remainingMs(iso) / 1000);
  if (total < 0) total = 0;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}
