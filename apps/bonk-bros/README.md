# BONK BROS

A silly face-swap brawler for Waleed, Tamer and Ameen.

Each kid photographs their own face, drops it on a footballer / monkey /
superhero / robot / ninja / wrestler, and then they smack each other around
with slaps, pies, fart blasts and one enormous signature move. There is also a
Talk Booth that repeats whatever they say in their character's voice, Talking
Tom style.

Nothing in it hurts. Everyone gets back up. The worst that happens is swirly
eyes and a cow falling out of the sky.

---

## Running it

You need Node 18 or newer on a laptop or desktop that stays on the same wifi as
the kids' devices.

```bash
cd apps/bonk-bros
npm install
npm start
```

It prints two addresses:

```
  This device : http://localhost:8080
  Kids' iPads : http://192.168.1.42:8080
```

Type the second one into Safari or Chrome on each kid's device. No app store, no
accounts, no sign-in. On iOS, **Share → Add to Home Screen** makes it open
fullscreen like a real app.

## First run

The opening screen asks **Who's playing?** and offers Waleed, Tamer and Ameen
as one-tap characters. Waleed and Tamer already have their faces on (cropped
from the dodgeball photo); Ameen goes straight to the Face Booth so he can take
his own. Everything about a starter is editable afterwards, photo included, and
"Somebody else" builds one from scratch.

To change who the starters are, edit `public/js/starters.js` and drop matching
crops into `public/faces/`.

## Playing together

- **Party fight** — one kid taps *Start a new party* and reads out the four
  letter code. The others tap *Join*, type the code, and everybody sees each
  other in the lobby. Up to six players, 2–6 in a free-for-all. Tap a brother's
  face to pick who you are bonking.
- **Couch fight** — 2 to 4 goofballs on one screen, each with their own set of
  buttons. Good for an iPad on the floor.
- **Fight a robot** — practise on your own against a deliberately mediocre
  opponent.
- **Talk Booth** — hold the big green button, say something daft, and your
  goofball repeats it. Swap voices to hear the same clip as a chipmunk, a
  robot, a swamp monster. Poke, tickle and slap buttons make it react. If you
  are in a party, everyone hears it.

The player who started the party is the "host" — their browser runs the fight
and tells everyone else what happened, so all the devices agree. The server
itself only passes messages along.

## The microphone needs https

Browsers refuse microphone access on a plain `http://` page. Everything else
works fine without it — photos come from the phone's own camera app, and
characters still talk using the built-in speech voices — but **recording your
own voice needs https**.

To turn it on:

```bash
npm run cert         # needs openssl; writes .cert/
npm run start:https
```

Then use `https://192.168.1.42:8080` instead. Each device will warn once that
the connection "is not private" — that is expected, because the certificate was
made on your own machine rather than bought from anybody. Tap through it
(**Advanced → Continue**). On iPhones and iPads Safari is stricter: install the
certificate via **Settings → General → VPN & Device Management**, then switch it
on under **Settings → General → About → Certificate Trust Settings**. If that is
more hassle than it is worth, just run plain `npm start` and use the built-in
voices.

## Where the kids' photos go

Two cropped photos ship with the game, in `public/faces/`, so Waleed and Tamer
can start playing without doing anything. Those two are committed to this
repository. Delete the files and blank the `face` fields in
`public/js/starters.js` if you would rather they weren't.

Every other photo — anything taken in the Face Booth — is cropped in the
browser and kept in that device's own local storage. It is never uploaded,
never written to disk on the server, and never leaves your wifi. When a kid
joins a party their character (including the face) is passed to the other
players in the room so it can be drawn on their screens, and it is dropped as
soon as everyone disconnects.

Deleting a goofball in *My goofballs* deletes its photo with it.

## Layout

```
server/
  index.js       static files + a websocket relay, keyed by room code
  make-cert.js   self-signed certificate for the microphone
public/
  index.html
  faces/         the two cropped starter photos
  css/style.css
  js/
    main.js        screen router: title, who's playing, home, roster, party
    starters.js    the ready-made brothers
    characters.js  the character model and all of the SVG artwork
    fight.js       the rules — health, moves, cooldowns, silly events
    arena.js       the fight screen: animation, effects, control pads
    lab.js         Character Lab
    facebooth.js   photo capture and the round crop
    talkbooth.js   Talk Booth
    voice.js       recording, pitch shifting, speech
    sfx.js         every sound effect, generated with the Web Audio API
    net.js         websocket client and room protocol
    store.js       local storage
    ui.js          small DOM helpers
```

There are no build steps and no front-end dependencies. `ws` on the server is
the only package.

### Adding a new move

Add it to `MOVES` in `fight.js` (damage range, cooldown, stun, sound, comic
word), then add a colour for `.move-<id>` in `style.css`. It appears on every
control pad automatically.

### Adding a new species

Add an entry to `SPECIES` in `characters.js` with its signature move, then give
it a torso in `bodyFor()`. Everything else — the lab chips, the control pad,
the arena — reads from that object.
