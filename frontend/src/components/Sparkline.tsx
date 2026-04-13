type SparklineProps = {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  fill?: boolean;
};

export function Sparkline({ values, width = 120, height = 40, color = 'var(--teal)', fill = true }: SparklineProps) {
  if (values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const pad = 2;
  const w = width - pad * 2;
  const h = height - pad * 2;

  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * w;
    const y = pad + h - ((v - min) / range) * h;
    return `${x},${y}`;
  });

  const polyline = pts.join(' ');
  const last = pts[pts.length - 1].split(',');
  const first = pts[0].split(',');

  const fillPath = fill
    ? `M${first[0]},${pad + h} L${pts.join(' L')} L${last[0]},${pad + h} Z`
    : null;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block', overflow: 'visible' }}>
      {fillPath && (
        <path
          d={fillPath}
          fill={color}
          opacity={0.12}
        />
      )}
      <polyline
        points={polyline}
        fill="none"
        stroke={color}
        strokeWidth={1.8}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle
        cx={last[0]}
        cy={last[1]}
        r={3}
        fill={color}
      />
    </svg>
  );
}
