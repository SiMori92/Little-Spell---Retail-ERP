import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import {
  artworks,
  artworkStorageKey,
  createArtworkShuffler,
} from "../src/lib/artwork";

function session() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

it("shows every work once per cycle with no repeat across cycle boundaries", () => {
  const next = createArtworkShuffler();
  const storage = session();
  let last: string | null = null;
  for (let cycle = 0; cycle < 100; cycle++) {
    const seen = new Set<string>();
    for (let visit = 0; visit < artworks.length; visit++) {
      const artwork = next(storage);
      expect(artwork.id).not.toBe(last);
      seen.add(artwork.id);
      last = artwork.id;
    }
    expect(seen.size).toBe(artworks.length);
  }
});

it("preserves the unfinished bag across refreshes and avoids a boundary repeat", () => {
  const storage = session();
  const visits = Array.from(
    { length: artworks.length },
    () => createArtworkShuffler(() => 0.999)(storage).id,
  );
  expect(new Set(visits).size).toBe(artworks.length);
  expect(createArtworkShuffler(() => 0.999)(storage).id).not.toBe(
    visits.at(-1),
  );
  storage.setItem(
    artworkStorageKey,
    JSON.stringify({ remaining: [], last: artworks[0]!.id }),
  );
  expect(createArtworkShuffler(() => 0.999)(storage).id).not.toBe(
    artworks[0]!.id,
  );
});

it.each([
  "{broken JSON",
  "null",
  JSON.stringify({ remaining: ["removed-artwork"], last: null }),
  JSON.stringify({ remaining: [artworks[0]!.id, artworks[0]!.id], last: null }),
  JSON.stringify({ remaining: [artworks[0]!.id], last: artworks[0]!.id }),
])("recovers from invalid or outdated stored state: %s", (stored) => {
  const storage = session();
  storage.setItem(artworkStorageKey, stored);
  expect(artworks).toContain(createArtworkShuffler()(storage));
});

it("keeps shuffling when reading or writing session storage is blocked", () => {
  const next = createArtworkShuffler();
  const blocked = {
    getItem: () => {
      throw new Error("Blocked");
    },
    setItem: () => {
      throw new Error("Blocked");
    },
  };
  const visits = Array.from(
    { length: artworks.length },
    () => next(blocked).id,
  );
  expect(new Set(visits).size).toBe(artworks.length);
});

it("rotates at least 100 unique works with Google Arts & Culture references", () => {
  expect(artworks.length).toBeGreaterThanOrEqual(100);
  expect(new Set(artworks.map((artwork) => artwork.id)).size).toBe(
    artworks.length,
  );
  for (const artwork of artworks) {
    expect(new URL(artwork.source).hostname).toBe("artsandculture.google.com");
    expect(artwork.title).toBeTruthy();
    expect(artwork.artist).toBeTruthy();
    expect(artwork.year).toBeTruthy();
  }
});

it("leads with a real local JPEG offline fallback", () => {
  const fallback = artworks[0]!;
  expect(fallback.image.startsWith("/art/")).toBe(true);
  const bytes = readFileSync(
    new URL(`../public${fallback.image}`, import.meta.url),
  );
  expect([...bytes.subarray(0, 3)]).toEqual([0xff, 0xd8, 0xff]);
});

it("points every remote work at a reachable Wikimedia Commons thumbnail", () => {
  for (const artwork of artworks.slice(1)) {
    const image = new URL(artwork.image);
    expect(image.protocol).toBe("https:");
    expect(image.hostname).toBe("thumb.wikimedia.org");
    expect(image.pathname).toMatch(/\.jpe?g$/i);
  }
});
