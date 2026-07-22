import { memo } from "react";
import type { ChartCoordinates } from "../chart/ChartAdapter";
import type { DrawingState } from "../chart/chartState";

interface Props {
  drawings: DrawingState[];
  coordinates: ChartCoordinates;
  tickSize: number;
  renderVersion: number;
}

export const DrawingOverlay = memo(function DrawingOverlay({
  drawings,
  coordinates,
  tickSize,
  renderVersion
}: Props) {
  void renderVersion;
  return (
    <svg className="drawing-overlay">
      {drawings.map(drawing => renderDrawing(drawing, coordinates, tickSize))}
    </svg>
  );
});

function renderDrawing(
  state: DrawingState,
  coordinates: ChartCoordinates,
  tickSize: number
): React.ReactNode {
  const drawing = state.payload;
  if (drawing.visible === false) return null;
  const kind = String(drawing.kind);
  if (kind === "trend_line") {
    const start = drawing.start as Point;
    const end = drawing.end as Point;
    const x1 = coordinates.timeToX(Number(start.time_ns));
    const x2 = coordinates.timeToX(Number(end.time_ns));
    const y1 = coordinates.priceToY(Number(start.price_ticks) * tickSize);
    const y2 = coordinates.priceToY(Number(end.price_ticks) * tickSize);
    if (x1 === null || x2 === null || y1 === null || y2 === null) return null;
    const appearance = drawing.appearance as Appearance;
    return (
      <line
        key={state.drawingId}
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        stroke={appearance.color}
        strokeWidth={appearance.width}
        strokeDasharray={dash(appearance.style)}
      />
    );
  }
  if (kind === "horizontal_line") {
    const y = coordinates.priceToY(Number(drawing.price_ticks) * tickSize);
    if (y === null) return null;
    const appearance = drawing.appearance as Appearance;
    return (
      <g key={state.drawingId}>
        <line
          x1="0"
          x2="100%"
          y1={y}
          y2={y}
          stroke={appearance.color}
          strokeWidth={appearance.width}
          strokeDasharray={dash(appearance.style)}
        />
        {drawing.label ? <text x="8" y={y - 5} fill={appearance.color}>{String(drawing.label)}</text> : null}
      </g>
    );
  }
  if (kind === "rectangle") {
    const start = drawing.start as Point;
    const end = drawing.end as Point;
    const x1 = coordinates.timeToX(Number(start.time_ns));
    const x2 = coordinates.timeToX(Number(end.time_ns));
    const y1 = coordinates.priceToY(Number(start.price_ticks) * tickSize);
    const y2 = coordinates.priceToY(Number(end.price_ticks) * tickSize);
    if (x1 === null || x2 === null || y1 === null || y2 === null) return null;
    const border = drawing.border as Appearance;
    const fill = drawing.fill as Fill;
    return (
      <rect
        key={state.drawingId}
        x={Math.min(x1, x2)}
        y={Math.min(y1, y2)}
        width={Math.abs(x2 - x1)}
        height={Math.abs(y2 - y1)}
        fill={fill.color}
        fillOpacity={Number(fill.opacity)}
        stroke={border.color}
        strokeWidth={border.width}
        strokeDasharray={dash(border.style)}
      />
    );
  }
  if (kind === "marker") {
    const x = coordinates.timeToX(Number(drawing.time_ns));
    const price = drawing.price_ticks;
    const y = price === null || price === undefined ? null : coordinates.priceToY(Number(price) * tickSize);
    if (x === null || y === null) return null;
    const position = String(drawing.position);
    const offset = position === "below_bar" ? 13 : -13;
    const color = String(drawing.color);
    return (
      <g key={state.drawingId} transform={`translate(${x} ${y + offset})`}>
        <path d={position === "below_bar" ? "M 0 -8 L 7 4 L -7 4 Z" : "M 0 8 L 7 -4 L -7 -4 Z"} fill={color} />
        {drawing.text ? <text x="10" y="4" fill={color}>{String(drawing.text)}</text> : null}
      </g>
    );
  }
  if (kind === "label") {
    const anchor = drawing.anchor as Point;
    const x = coordinates.timeToX(Number(anchor.time_ns));
    const y = coordinates.priceToY(Number(anchor.price_ticks) * tickSize);
    if (x === null || y === null) return null;
    return (
      <g key={state.drawingId} transform={`translate(${x} ${y})`}>
        <rect x="-4" y="-18" width={String(drawing.text).length * 7 + 8} height="22" rx="4" fill={String(drawing.background_color)} />
        <text x="0" y="-3" fill={String(drawing.text_color)}>{String(drawing.text)}</text>
      </g>
    );
  }
  if (kind === "risk_reward") {
    const entryTime = Number(drawing.entry_time_ns);
    const exitTime = Number(drawing.exit_time_ns ?? entryTime + 30 * 60 * 1_000_000_000);
    const x1 = coordinates.timeToX(entryTime);
    const x2 = coordinates.timeToX(exitTime);
    const entry = coordinates.priceToY(Number(drawing.entry_price_ticks) * tickSize);
    const stop = coordinates.priceToY(Number(drawing.stop_price_ticks) * tickSize);
    const target = coordinates.priceToY(Number(drawing.target_price_ticks) * tickSize);
    if (x1 === null || x2 === null || entry === null || stop === null || target === null) return null;
    const risk = drawing.risk_fill as Fill;
    const reward = drawing.reward_fill as Fill;
    const width = Math.max(20, Math.abs(x2 - x1));
    const x = Math.min(x1, x2);
    return (
      <g key={state.drawingId}>
        <rect x={x} y={Math.min(entry, stop)} width={width} height={Math.abs(stop - entry)} fill={risk.color} fillOpacity={Number(risk.opacity)} />
        <rect x={x} y={Math.min(entry, target)} width={width} height={Math.abs(target - entry)} fill={reward.color} fillOpacity={Number(reward.opacity)} />
        <line x1={x} x2={x + width} y1={entry} y2={entry} stroke={(drawing.entry_line as Appearance).color} />
        <line x1={x} x2={x + width} y1={stop} y2={stop} stroke={(drawing.stop_line as Appearance).color} />
        <line x1={x} x2={x + width} y1={target} y2={target} stroke={(drawing.target_line as Appearance).color} />
        {drawing.label ? <text x={x + 6} y={Math.min(entry, target) + 16} fill="#d8e0eb">{String(drawing.label)}</text> : null}
      </g>
    );
  }
  return null;
}

interface Point {
  time_ns: number;
  price_ticks: string | number;
}

interface Appearance {
  color: string;
  width: number;
  style: string;
}

interface Fill {
  color: string;
  opacity: string | number;
}

function dash(style: string): string | undefined {
  if (style === "dashed") return "8 5";
  if (style === "dotted") return "2 4";
  return undefined;
}
