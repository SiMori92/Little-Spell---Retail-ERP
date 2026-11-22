// Builds src/lib/artwork-catalog.json: a URL catalogue of public-domain
// Impressionist and Post-Impressionist paintings scanned by the Google Art
// Project and hosted on Wikimedia Commons. Each entry links to its Google Arts
// & Culture page for attribution. Run with: node scripts/build-art-catalog.mjs
// Adapted from the SetSail benchmark builder (UI_HANDBOOK.md, "Artwork system").
import { writeFile } from "node:fs/promises";

const api = "https://commons.wikimedia.org/w/api.php";
const userAgent =
  "LittleSpellArtCatalog/1.0 (header artwork catalogue; build-time only)";
const thumbWidth = 1280; // A standard Wikimedia thumbnail step.
const perArtist = 18; // Caps any one artist so the rotation stays varied.
const minimum = 100;

// Artists who died before 1930, so their works are public domain worldwide.
const artists = [
  "Claude Monet",
  "Pierre-Auguste Renoir",
  "Camille Pissarro",
  "Alfred Sisley",
  "Edgar Degas",
  "Gustave Caillebotte",
  "Berthe Morisot",
  "Mary Cassatt",
  "Édouard Manet",
  "Frédéric Bazille",
  "Armand Guillaumin",
  "Eugène Boudin",
  "Vincent van Gogh",
  "Paul Cézanne",
  "Georges Seurat",
  "Paul Signac",
  "Paul Gauguin",
  "Henri-Edmond Cross",
  "Henri de Toulouse-Lautrec",
  "Johan Barthold Jongkind",
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// Honour Retry-After when the server sends it; otherwise back off progressively.
function backoff(response, attempt) {
  const seconds = Number(response.headers.get("retry-after"));
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 5000 * (attempt + 1);
}

async function query(params) {
  const url = new URL(api);
  url.search = new URLSearchParams({
    format: "json",
    formatversion: "2",
    ...params,
  }).toString();
  for (let attempt = 0; ; attempt++) {
    await sleep(250); // Stay well inside Wikimedia's API etiquette.
    const response = await fetch(url, {
      headers: { "User-Agent": userAgent },
    });
    if (response.ok) return response.json();
    if (attempt >= 6) throw new Error(`${response.status} for ${url}`);
    await sleep(backoff(response, attempt));
  }
}

async function categoryFiles(artist) {
  const titles = [];
  let cont = {};
  do {
    const data = await query({
      action: "query",
      list: "categorymembers",
      cmtitle: `Category:Google Art Project works by ${artist}`,
      cmtype: "file",
      cmlimit: "500",
      ...cont,
    });
    titles.push(...(data.query?.categorymembers ?? []).map((m) => m.title));
    cont = data.continue ?? null;
  } while (cont);
  return titles.filter((title) => /\.jpe?g$/i.test(title)).sort();
}

function templateField(wikitext, name) {
  const match = wikitext.match(
    new RegExp(`\\|\\s*${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*=([^\\n|]*)`),
  );
  return match?.[1].trim() ?? "";
}

function clean(text) {
  return text
    .replace(/\{\{[^}]*\}\}/g, "")
    .replace(/\[\[(?:[^|\]]*\|)?([^\]]*)\]\]/g, "$1")
    .replace(/'{2,}/g, "") // Wiki italic/bold markup
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function slug(text) {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 70)
    .replace(/-$/, "");
}

async function describe(titles) {
  const pages = [];
  for (let i = 0; i < titles.length; i += 25) {
    const data = await query({
      action: "query",
      titles: titles.slice(i, i + 25).join("|"),
      prop: "imageinfo|revisions",
      rvprop: "content",
      rvslots: "main",
      iiprop: "url|size|extmetadata",
      iiurlwidth: String(thumbWidth),
    });
    pages.push(...(data.query?.pages ?? []));
  }
  return pages;
}

function toArtwork(page, artist) {
  const info = page.imageinfo?.[0];
  const wikitext = page.revisions?.[0]?.slots?.main?.content ?? "";
  if (!info || !wikitext.includes("{{Google Art Project")) return null;
  const meta = info.extmetadata ?? {};
  const license = meta.LicenseShortName?.value ?? "";
  if (!/public domain|cc0|pd/i.test(license)) return null;
  if (meta.Copyrighted?.value === "True") return null;
  if (templateField(wikitext, "object_work_type") !== "painting") return null;
  const assetId = templateField(wikitext, "special:url_id");
  if (!/^[\w-]{8,}$/.test(assetId)) return null;
  // The header is a wide, shallow crop; portrait canvases crop badly.
  if (info.width / info.height < 1.15 || info.thumbwidth < thumbWidth)
    return null;
  const title = clean(templateField(wikitext, "title"));
  const year = clean(
    templateField(wikitext, "pretty_display_date") ||
      templateField(wikitext, "earliest_date_display") ||
      meta.DateTimeOriginal?.value ||
      "",
  ).replace(/<[^>]+>/g, "");
  if (!title || !year || title.length > 90 || /^untitled$/i.test(title))
    return null;
  const thumb = new URL(info.thumburl);
  thumb.search = "";
  return {
    id: `${slug(artist)}-${slug(title)}`,
    artist,
    title,
    year,
    image: thumb.toString(),
    source: `https://artsandculture.google.com/asset/${assetId}`,
    commons: info.descriptionurl,
    license: license === "Public domain" ? "Public domain (PD-Art)" : license,
    collection: clean(templateField(wikitext, "collection_display_name")),
  };
}

async function reachable(url) {
  for (let attempt = 0; attempt < 5; attempt++) {
    await sleep(150);
    const response = await fetch(url, {
      method: "HEAD",
      headers: { "User-Agent": userAgent },
    });
    if (response.ok)
      return /^image\/jpe?g/.test(response.headers.get("content-type") ?? "");
    if (response.status !== 429 && response.status < 500) return false;
    await sleep(backoff(response, attempt));
  }
  return false;
}

const catalog = [];
const seen = new Set();
for (const artist of artists) {
  const files = await categoryFiles(artist);
  const works = (await describe(files))
    .map((page) => toArtwork(page, artist))
    .filter(Boolean);
  let added = 0;
  for (const work of works) {
    if (added >= perArtist) break;
    const key = `${slug(work.title)}|${work.year}`;
    if (seen.has(work.id) || seen.has(key)) continue;
    if (!(await reachable(work.image))) continue;
    seen.add(work.id).add(key);
    catalog.push(work);
    added++;
  }
  console.log(`${artist}: ${added} of ${files.length} files`);
}

if (catalog.length < minimum)
  throw new Error(`Only ${catalog.length} works; at least ${minimum} required.`);
await writeFile(
  new URL("../src/lib/artwork-catalog.json", import.meta.url),
  `${JSON.stringify(catalog, null, 2)}\n`,
);
console.log(`Wrote ${catalog.length} works to src/lib/artwork-catalog.json`);
