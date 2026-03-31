import type { ReactNode } from 'react';

type StatusPillProps = {
  tone: 'ok' | 'warn' | 'error' | 'neutral';
  children: ReactNode;
};

export function StatusPill({ tone, children }: StatusPillProps) {
  return <span className={`status-pill ${tone}`}>{children}</span>;
}
