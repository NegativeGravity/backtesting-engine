import { BoxSelect, Crosshair, Minus, MousePointer2, Ruler, Tag, TrendingUp } from "lucide-react";

const tools = [
  { label: "Cursor", icon: MousePointer2 },
  { label: "Crosshair", icon: Crosshair },
  { label: "Trend line", icon: TrendingUp },
  { label: "Horizontal line", icon: Minus },
  { label: "Rectangle", icon: BoxSelect },
  { label: "Measure", icon: Ruler },
  { label: "Label", icon: Tag }
];

export function ToolRail() {
  return (
    <aside className="tool-rail">
      {tools.map(({ label, icon: Icon }, index) => (
        <button key={label} className={`tool-button ${index === 0 ? "active" : ""}`} title={label}>
          <Icon size={17} />
        </button>
      ))}
    </aside>
  );
}
