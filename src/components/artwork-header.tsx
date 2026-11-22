'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { artworkFallback, createArtworkShuffler, type Artwork } from '@/lib/artwork';

const nextArtwork = createArtworkShuffler();

export function ArtworkHeader() {
  const pathname = usePathname();
  const [artwork, setArtwork] = useState<Artwork | null>(null);

  useEffect(() => {
    let disposed = false;
    let pending: HTMLImageElement | null = null;
    function selectArtwork() {
      let storage: Storage | null = null;
      try { storage = window.sessionStorage; } catch { /* In-memory shuffle. */ }
      const selected = nextArtwork(storage);
      if (pending) pending.onload = pending.onerror = null;
      const image = new Image();
      pending = image;
      image.onload = () => { if (!disposed) setArtwork(selected); };
      // A failed remote load falls back to the first catalogued work, the one
      // local image, so the header still shows a painting offline. The caption
      // always matches the displayed image; if even the fallback fails, the
      // neutral panel keeps the working area stable and unattributed.
      image.onerror = () => {
        if (disposed) return;
        if (selected.id === artworkFallback.id) { setArtwork(null); return; }
        const retry = new Image();
        pending = retry;
        retry.onload = () => { if (!disposed) setArtwork(artworkFallback); };
        retry.onerror = () => { if (!disposed) setArtwork(null); };
        retry.src = artworkFallback.image;
      };
      image.src = selected.image;
    }
    queueMicrotask(() => { if (!disposed) selectArtwork(); });
    function onPageShow(event: PageTransitionEvent) {
      if (event.persisted) selectArtwork();
    }
    window.addEventListener('pageshow', onPageShow);
    return () => {
      disposed = true;
      if (pending) pending.onload = pending.onerror = null;
      window.removeEventListener('pageshow', onPageShow);
    };
  }, [pathname]);

  return <div className="page-heading-art" style={artwork ? { backgroundImage: `url("${artwork.image}")` } : undefined}>
    {artwork && <a href={artwork.source} target="_blank" rel="noopener noreferrer"
      aria-label={`${artwork.title} by ${artwork.artist}, ${artwork.year}. Explore on Google Arts & Culture (opens in a new tab).`}>
      {artwork.artist} · {artwork.title}, {artwork.year}
    </a>}
  </div>;
}
