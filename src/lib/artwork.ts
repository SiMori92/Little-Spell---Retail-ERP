import catalog from "./artwork-catalog.json";

export type Artwork = {
  id: string;
  artist: string;
  title: string;
  year: string;
  image: string;
  source: string;
};

// The only locally stored image. It leads the catalogue so a failed remote
// load can fall back to a painting that renders without network access.
const offlineFallback: Artwork = {
  id: "monet-water-lilies",
  artist: "Claude Monet",
  title: "Water Lilies",
  year: "1906",
  image: "/art/monet-water-lilies.jpg",
  source: "https://artsandculture.google.com/asset/XwEbNDsEYukiWQ",
};

// URL catalogue of Google Art Project scans hosted on Wikimedia Commons,
// built by scripts/build-art-catalog.mjs. Every entry is public domain and
// links to its Google Arts & Culture reference for attribution.
export const artworks: Artwork[] = [offlineFallback, ...catalog];
export const artworkFallback = artworks[0]!;

type ShuffleState = { remaining: string[]; last: string | null };
type ArtStorage = Pick<Storage, "getItem" | "setItem">;
export const artworkStorageKey = "little-spell-artwork-shuffle-v2";
const ids: string[] = artworks.map((artwork) => artwork.id);

function readState(value: string | null): ShuffleState | null {
  if (!value) return null;
  try {
    const state: unknown = JSON.parse(value);
    if (!state || typeof state !== "object") return null;
    const { remaining, last } = state as Partial<ShuffleState>;
    if (
      !Array.isArray(remaining) ||
      !remaining.every((id) => typeof id === "string" && ids.includes(id)) ||
      new Set(remaining).size !== remaining.length ||
      !(last === null || (typeof last === "string" && ids.includes(last))) ||
      (last !== null && remaining.includes(last))
    )
      return null;
    return { remaining, last };
  } catch {
    return null;
  }
}

// Each complete bag contains every work once. The next bag cannot start with
// the previous bag's final work. In-memory state also supports blocked storage.
export function createArtworkShuffler(random = Math.random) {
  let memory: ShuffleState = { remaining: [], last: null };
  return (storage?: ArtStorage | null): Artwork => {
    let state = memory;
    try {
      state = readState(storage?.getItem(artworkStorageKey) ?? null) ?? memory;
    } catch {
      /* Storage may be blocked by browser settings. */
    }
    const remaining = [...state.remaining];
    if (!remaining.length) {
      remaining.push(...ids);
      for (let i = remaining.length - 1; i > 0; i--) {
        const j = Math.floor(random() * (i + 1));
        [remaining[i], remaining[j]] = [remaining[j]!, remaining[i]!];
      }
      if (remaining.length > 1 && remaining[0] === state.last) {
        const j = 1 + Math.floor(random() * (remaining.length - 1));
        [remaining[0], remaining[j]] = [remaining[j]!, remaining[0]!];
      }
    }
    const id = remaining.shift()!;
    memory = { remaining, last: id };
    try {
      storage?.setItem(artworkStorageKey, JSON.stringify(memory));
    } catch {
      /* The in-memory bag still avoids repeats during navigation. */
    }
    return artworks.find((artwork) => artwork.id === id)!;
  };
}
