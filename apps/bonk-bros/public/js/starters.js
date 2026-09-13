/**
 * Ready-made goofballs, so a kid can open the game and just tap their own name.
 *
 * `face` points at a cropped photo in public/faces/. It is loaded and turned
 * into a data URL when the starter is picked, so from that moment the
 * character is identical to one built in the Face Booth — same storage, same
 * editing, same "retake my photo" button. A starter with no face goes straight
 * to the Face Booth instead.
 */

export const STARTERS = [
  {
    name: 'Waleed',
    face: 'faces/waleed.jpg',
    species: 'footballer',
    outfit: '#d92b2b',
    hat: 'helmet',
    voice: 'coach',
    number: '11',
    headSize: 'big',
    catchphrase: 'Dodgeball champion coming through!'
  },
  {
    name: 'Tamer',
    face: 'faces/tamer.jpg',
    species: 'monkey',
    outfit: '#f0a830',
    skin: '#a9743f',
    hat: 'cap',
    voice: 'chipmunk',
    headSize: 'big',
    catchphrase: 'Ooh ooh aah aah, you smell like a banana!'
  },
  {
    name: 'Ameen',
    face: 'faces/ameen.jpg',
    species: 'superhero',
    outfit: '#8b2fd6',
    hat: 'crown',
    voice: 'squeak',
    headSize: 'big',
    bodySize: 'shrimp',
    catchphrase: 'I am the smallest AND the strongest!'
  }
];

/**
 * Reads a starter's photo off the server and returns it as a data URL, so it
 * lands in local storage exactly like a Face Booth photo does.
 * @returns {Promise<string|null>} null if there is no photo, or it won't load
 */
export async function loadStarterFace(starter) {
  if (!starter.face) return null;
  try {
    const response = await fetch(starter.face, { cache: 'force-cache' });
    if (!response.ok) return null;
    let blob = await response.blob();
    if (!blob.type.startsWith('image/')) {
      // Some static hosts serve unknown extensions as octet-stream. These
      // paths are ours, not user input, so trust the extension and re-tag it.
      const guess = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp' }[
        starter.face.split('.').pop().toLowerCase()
      ];
      if (!guess) return null;
      blob = new Blob([blob], { type: guess });
    }
    return await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(blob);
    });
  } catch {
    return null;
  }
}
