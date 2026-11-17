'use client';
import * as Tooltip from '@radix-ui/react-tooltip';
import { CircleHelp } from 'lucide-react';
import glossary from './glossary.json';
export function Glossary({ term }: { term: keyof typeof glossary }) {
  return <Tooltip.Provider><Tooltip.Root><Tooltip.Trigger asChild><button className="icon-button" aria-label={`Explain ${term}`}><CircleHelp size={14} /></button></Tooltip.Trigger><Tooltip.Portal><Tooltip.Content className="glossary" sideOffset={6}>{glossary[term]}</Tooltip.Content></Tooltip.Portal></Tooltip.Root></Tooltip.Provider>;
}
