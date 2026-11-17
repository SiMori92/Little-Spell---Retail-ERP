'use client';
export default function ErrorPage({ reset }: { reset:() => void }) {
  return <section className="card"><h1>We couldn’t open this page</h1><p>No partial record was booked. Retry, or check your local data folder permissions.</p><button className="button" onClick={reset}>Try again</button></section>;
}
