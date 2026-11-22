# Header artwork

The shared header selects a painting on each route visit, refresh, or return via the browser's back/forward cache. A shuffled bag in sessionStorage (`little-spell-artwork-shuffle-v2`) shows every catalogued work once before starting another cycle and avoids an immediate repeat between cycles. Normal polling and filter changes do not reshuffle. When browser storage is blocked, an in-memory bag supports navigation; reload history cannot be retained in that case.

## Collection

The rotation is a URL catalogue of **111 public-domain Impressionist and Post-Impressionist works** in [`src/lib/artwork-catalog.json`](../../src/lib/artwork-catalog.json), plus the one local fallback below (112 works per bag). Every entry was scanned by the **Google Art Project** and is hosted on Wikimedia Commons; the catalogue is built at development time by [`scripts/build-art-catalog.mjs`](../../scripts/build-art-catalog.mjs), never fetched live at runtime.

The builder walks the Wikimedia Commons categories `Google Art Project works by <artist>` for 20 artists who died before 1930 (public domain worldwide), keeps only landscape paintings with a verified public-domain licence, a Google Arts & Culture asset link, and a reachable 1280px-wide JPEG thumbnail, and caps any one artist at 18 works so the rotation stays varied. It refuses to write fewer than 100 works.

Per-work attribution lives in the catalogue itself: each entry carries `artist`, `title`, `year`, `image` (Wikimedia thumbnail URL), `source` (Google Arts & Culture asset page), `commons` (Wikimedia file page), `license` (`Public domain (PD-Art)`), and `collection` (holding museum). Captions display artist, title, and year and open the matching Google Arts & Culture reference in a new tab (`noopener noreferrer`). Google Arts & Culture is the discovery/reference destination, not a live image feed; the images render from Wikimedia Commons thumbnails.

Current mix: Monet 18, Cézanne 18, van Gogh 15, Renoir 10, Gauguin 9, Manet 8, Signac 6, Degas 5, Pissarro 5, Caillebotte 3, Seurat 3, Sisley 3, Toulouse-Lautrec 3, and one each from Cassatt, Bazille, Boudin, Cross, and Jongkind.

## Offline fallback

Only one image is stored locally. It is the first catalogue entry, so a failed remote load falls back to a painting that renders without network access; if even it fails, the header shows a neutral panel with no caption.

| Local file               | Work                               | Google Arts & Culture                                  | Image source / rights                                                                                                                           |
| ------------------------ | ---------------------------------- | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `monet-water-lilies.jpg` | Claude Monet, _Water Lilies_, 1906 | https://artsandculture.google.com/asset/XwEbNDsEYukiWQ | https://commons.wikimedia.org/wiki/File:Claude_Monet_-_Water_Lilies_-_1906,_Ryerson.jpg · Public domain; Art Institute of Chicago artwork 16568 |

Museum public-domain status for the Chicago work was verified through `https://api.artic.edu/api/v1/artworks/16568?fields=id,title,is_public_domain`. The local JPEG is resized to a maximum edge of 1200 pixels; remote thumbnails are 1280px wide. All images are cropped by CSS for the decorative header.

## Maintaining the catalogue

Regenerate with `node scripts/build-art-catalog.mjs` (build-time only; it pauses between requests and honours Wikimedia's `Retry-After`). Review the desktop and shallow mobile crops of new entries, then bump `artworkStorageKey` in `src/lib/artwork.ts` so existing sessions start a fresh bag, and run the artwork tests. A new work needs its own verified reuse rights; its appearance on Google does not establish permission to copy it.
