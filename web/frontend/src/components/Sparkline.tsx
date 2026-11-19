interface Props {
  data: number[];
  height?: number;
  color?: string;
  fill?: boolean;
}

export function Sparkline({ data, height = 54, color = "#22d3ee", fill = true }: Props) {
  if (data.length < 2) {
    return (
      <div className="sparkline-empty" style={{ height }}>
        waiting for bars…
      </div>
    );
  }

  const w = 100;
  const pad = 3;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - pad * 2);
    const y = height - pad - ((v - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  const line = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const area = `${line} L${pts[pts.length - 1][0].toFixed(2)},${height} L${pts[0][0].toFixed(2)},${height} Z`;

  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${w} ${height}`}
      preserveAspectRatio="none"
      style={{ height }}
    >
      {fill && <path d={area} fill={color} opacity={0.12} />}
      <path d={line} fill="none" stroke={color} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
