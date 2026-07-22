import { memo, useRef } from "react";

interface Props {
  axis: "x" | "y";
  value: number;
  minimum: number;
  maximum: number;
  direction?: 1 | -1;
  onChange: (value: number) => void;
  label: string;
}

export const ResizeHandle = memo(function ResizeHandle({
  axis,
  value,
  minimum,
  maximum,
  direction = 1,
  onChange,
  label
}: Props) {
  const frameRef = useRef<number | null>(null);
  const pendingRef = useRef<number | null>(null);

  const startResize = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const start = axis === "x" ? event.clientX : event.clientY;
    const startValue = value;

    const flush = () => {
      frameRef.current = null;
      if (pendingRef.current === null) return;
      onChange(pendingRef.current);
      pendingRef.current = null;
    };

    const move = (moveEvent: PointerEvent) => {
      const current = axis === "x" ? moveEvent.clientX : moveEvent.clientY;
      const next = Math.min(maximum, Math.max(minimum, startValue + (current - start) * direction));
      pendingRef.current = Math.round(next);
      if (frameRef.current === null) frameRef.current = requestAnimationFrame(flush);
    };

    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
      if (pendingRef.current !== null) onChange(pendingRef.current);
      pendingRef.current = null;
      document.body.classList.remove("is-resizing");
    };

    document.body.classList.add("is-resizing");
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("pointerup", end, { once: true });
    window.addEventListener("pointercancel", end, { once: true });
  };

  return (
    <div
      className={`resize-handle resize-${axis}`}
      role="separator"
      aria-label={label}
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      tabIndex={0}
      onPointerDown={startResize}
    />
  );
});
