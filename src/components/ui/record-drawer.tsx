'use client';

import { useRef, type ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { Button } from './button';

export function RecordDrawer({ open, onOpenChange, title, description, closeLabel, children }: {
  open: boolean; onOpenChange: (open: boolean) => void; title: string; description: string; closeLabel: string; children: ReactNode;
}) {
  const opener = useRef<Element | null>(null);
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal>
    <Dialog.Overlay className="drawer-overlay" />
    <Dialog.Content className="record-drawer" onCloseAutoFocus={event => {
      // These drawers open from table buttons rather than a Dialog.Trigger.
      // Restore the exact opener captured when focus entered the dialog.
      if (opener.current instanceof HTMLElement && opener.current.isConnected) {
        event.preventDefault();
        opener.current.focus();
      }
    }} onOpenAutoFocus={() => { opener.current = document.activeElement; }}>
      <header className="drawer-header"><div><Dialog.Title>{title}</Dialog.Title><Dialog.Description>{description}</Dialog.Description></div>
        <Dialog.Close asChild><button type="button" className="icon-button" aria-label="Close record panel"><X size={18} /></button></Dialog.Close>
      </header>
      <div className="drawer-body">{children}</div>
      <footer className="drawer-footer"><Dialog.Close asChild><Button variant="secondary">{closeLabel}</Button></Dialog.Close></footer>
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>;
}

