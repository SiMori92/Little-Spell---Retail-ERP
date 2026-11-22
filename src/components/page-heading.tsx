import type { ReactNode } from 'react';
import { ArtworkHeader } from './artwork-header';

export function PageHeading({ eyebrow, title, description, action, compact = false }: {
  eyebrow: string; title: string; description: ReactNode; action?: ReactNode; compact?: boolean;
}) {
  return <header className={`page-heading painted-heading${compact ? ' compact compact-heading' : ''}`}>
    <div className="page-heading-copy">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p className="page-description">{description}</p>
      {action && <div className="heading-actions page-heading-action">{action}</div>}
    </div>
    <ArtworkHeader />
  </header>;
}
