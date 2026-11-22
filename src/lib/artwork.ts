export const artworks = [
  {
    id: "monet-water-lilies",
    artist: "Claude Monet",
    title: "Water Lilies",
    year: "1906",
    image: "/art/monet-water-lilies.jpg",
    source: "https://artsandculture.google.com/asset/XwEbNDsEYukiWQ",
  },
  {
    id: "monet-japanese-footbridge",
    artist: "Claude Monet",
    title: "The Japanese Footbridge",
    year: "1899",
    image: "/art/monet-japanese-footbridge.jpg",
    source: "https://artsandculture.google.com/asset/RgG90GYz4QkZ4A",
  },
  {
    id: "caillebotte-paris-rainy-day",
    artist: "Gustave Caillebotte",
    title: "Paris Street; Rainy Day",
    year: "1877",
    image: "/art/caillebotte-paris-rainy-day.jpg",
    source: "https://artsandculture.google.com/asset/5wEUCOlEf-EaVQ",
  },
  {
    id: "pissarro-boulevard-montmartre",
    artist: "Camille Pissarro",
    title: "The Boulevard Montmartre on a Winter Morning",
    year: "1897",
    image: "/art/pissarro-boulevard-montmartre.jpg",
    source: "https://artsandculture.google.com/asset/4wGJB3rAyAmk2w",
  },
] as const;

export type Artwork = (typeof artworks)[number];
type ShuffleState = { remaining: string[]; last: string | null };
type ArtStorage = Pick<Storage, "getItem" | "setItem">;
export const artworkStorageKey = "little-spell-artwork-shuffle-v1";
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
