import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { METRIC_COLORS, formatMetric, formatTimesteps } from "../lib/format";

export interface ChartSeries {
  key: string;
  label: string;
  points: [number, number][];
  color?: string;
}

interface MetricChartProps {
  series: ChartSeries[];
  height?: number;
}

export default function MetricChart({ series, height = 320 }: MetricChartProps) {
  const rowsByName = new Map<number, Record<string, number | string>>();
  series.forEach((item, index) => {
    const dataKey = `s${index}`;
    item.points.forEach(([timestep, value]) => {
      const row = rowsByName.get(timestep) ?? { timestep };
      row[dataKey] = value;
      rowsByName.set(timestep, row);
    });
  });
  const data = [...rowsByName.values()].sort((a, b) => Number(a.timestep) - Number(b.timestep));

  if (!series.length || !data.length) {
    return <div className="empty-state">No data points yet.</div>;
  }

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 18, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#21262d" />
          <XAxis
            dataKey="timestep"
            tickFormatter={(value: number) => formatTimesteps(value)}
            stroke="#8b949e"
            tick={{ fill: "#8b949e", fontSize: 11 }}
            minTickGap={30}
          />
          <YAxis
            stroke="#8b949e"
            tick={{ fill: "#8b949e", fontSize: 11 }}
            tickFormatter={(value: number) => formatMetric(value, 2)}
            width={62}
          />
          <Tooltip
            contentStyle={{ background: "#161b22", border: "1px solid #30363d", borderRadius: 8 }}
            labelStyle={{ color: "#c9d1d9" }}
            itemStyle={{ color: "#c9d1d9" }}
            labelFormatter={(value) => `timestep ${formatTimesteps(Number(value))}`}
            formatter={(value: number | string, name: string) => [formatMetric(Number(value), 4), name]}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "#8b949e" }} />
          {series.map((item, index) => (
            <Line
              key={item.key}
              type="monotone"
              dataKey={`s${index}`}
              name={item.label}
              stroke={item.color ?? METRIC_COLORS[index % METRIC_COLORS.length]}
              dot={false}
              strokeWidth={1.8}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
