/**
 * Everything a kid makes lives in their own browser. Faces never touch the
 * server unless they join a party, and then only the other players' browsers
 * see them.
 */

const KEY = 'bonkbros:v1';

const DEFAULTS = {
  characters: [],
  activeId: null,
  muted: false,
  seenIntro: false,
  wins: {}        // character id -> brawls won, for the family scoreboard
};

function read() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULTS };
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULTS };
  }
}

let state = read();

function write() {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch (err) {
    // Photos are the only big thing in here. If we blow the quota, drop the
    // oldest characters rather than losing everything.
    if (state.characters.length > 1) {
      state.characters = state.characters.slice(-3);
      try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* give up quietly */ }
    }
  }
}

export function getCharacters() {
  return state.characters;
}

export function getActive() {
  return state.characters.find((c) => c.id === state.activeId) || state.characters[0] || null;
}

export function setActive(id) {
  state.activeId = id;
  write();
}

export function saveCharacter(character) {
  const index = state.characters.findIndex((c) => c.id === character.id);
  if (index >= 0) state.characters[index] = character;
  else state.characters.push(character);
  state.activeId = character.id;
  write();
  return character;
}

export function deleteCharacter(id) {
  state.characters = state.characters.filter((c) => c.id !== id);
  if (state.activeId === id) state.activeId = state.characters[0]?.id || null;
  if (state.wins?.[id]) {
    const { [id]: _gone, ...rest } = state.wins;
    state.wins = rest;
  }
  write();
}

/**
 * Tally a win. Only for goofballs saved on THIS device — in a party every
 * device sees the same winner, and we do not want a phantom row for a brother
 * whose character lives in his own browser.
 */
export function recordWin(characterId) {
  if (!characterId || !state.characters.some((c) => c.id === characterId)) return;
  state.wins = { ...state.wins, [characterId]: (state.wins[characterId] || 0) + 1 };
  write();
}

/** [{ character, wins }], most wins first. Everybody appears, even on zero. */
export function getScoreboard() {
  return state.characters
    .map((character) => ({ character, wins: state.wins?.[character.id] || 0 }))
    .sort((a, b) => b.wins - a.wins || a.character.name.localeCompare(b.character.name));
}

export function resetScoreboard() {
  state.wins = {};
  write();
}

export function getSetting(key) {
  return state[key];
}

export function setSetting(key, value) {
  state[key] = value;
  write();
}
