import { pct } from "../format";

interface Props {
  prob: number | null | undefined;
  threshold?: number;
}

export function ProbGauge({ prob, threshold = 0.55 }: Props) {
  const p = prob === null || prob === undefined || !Number.isFinite(prob) ? 0.5 : prob;
  const cx = 70;
  const cy = 78;
  const r = 52;
  const color = p >= threshold ? "#34d399" : p <= 1 - threshold ? "#f87171" : "#7d8fa3";
  const arc = `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`;

  const thAngle = Math.PI * (1 - threshold);
  const tx1 = cx + (r - 8) * Math.cos(thAngle);
  const ty1 = cy - (r - 8) * Math.sin(thAngle);
  const tx2 = cx + (r + 7) * Math.cos(thAngle);
  const ty2 = cy - (r + 7) * Math.sin(thAngle);

  return (
    <svg className="gauge" viewBox="0 0 140 92">
      <path d={arc} className="gauge-track" pathLength={100} />
      <path
        d={arc}
        className="gauge-value"
        pathLength={100}
        strokeDasharray={`${Math.max(0, Math.min(1, p)) * 100} 100`}
        style={{ stroke: color }}
      />
      <line x1={tx1} y1={ty1} x2={tx2} y2={ty2} className="gauge-threshold" />
      <text x={cx} y={cy - 16} textAnchor="middle" className="gauge-num">
        {pct(prob, 1)}
      </text>
      <text x={cx} y={cy - 2} textAnchor="middle" className="gauge-cap">
        P(up)
      </text>
      <text x={16} y={90} className="gauge-scale">0</text>
      <text x={118} y={90} className="gauge-scale" textAnchor="end">1</text>
    </svg>
  );
}
