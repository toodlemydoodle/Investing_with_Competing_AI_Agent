import { ReactNode } from 'react';

type StatCardProps = {
  label: string;
  value: string;
  detail?: string;
  accent?: 'gold' | 'teal' | 'red';
  children?: ReactNode;
};

export function StatCard({ label, value, detail, accent = 'gold', children }: StatCardProps) {
  return (
    <article className={`stat-card ${accent}`}>
      <p className="eyebrow">{label}</p>
      <h3>{value}</h3>
      {detail ? <p className="detail">{detail}</p> : null}
      {children}
    </article>
  );
}
