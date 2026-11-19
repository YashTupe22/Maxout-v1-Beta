import { useEffect, useRef } from "react";

interface Props {
  lines: string[];
  height?: number;
}

export function LogConsole({ lines, height = 340 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div className="console" ref={ref} style={{ height }}>
      {lines.length === 0 ? (
        <span className="console-idle">waiting for output…</span>
      ) : (
        lines.map((line, i) => (
          <div key={i} className={line.startsWith("[dashboard]") ? "console-sys" : undefined}>
            {line}
          </div>
        ))
      )}
    </div>
  );
}
