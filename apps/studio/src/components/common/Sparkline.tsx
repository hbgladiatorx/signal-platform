import { Area, AreaChart, ResponsiveContainer } from "recharts";

export function Sparkline({ data, positive = true, height = 36 }: { data: number[]; positive?: boolean; height?: number }) {
  const series = data.map((v, i) => ({ i, v }));
  const color = positive ? "var(--cyan)" : "var(--danger)";
  const id = `spark-${positive ? "p" : "n"}-${data.length}-${Math.round((data[0] ?? 0) * 100)}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={series} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor={color} stopOpacity={0.45} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} fill={`url(#${id})`} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
