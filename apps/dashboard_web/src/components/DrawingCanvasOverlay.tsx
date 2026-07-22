import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState
} from "react";
import type { LightweightChartsAdapter } from "../chart/LightweightChartsAdapter";
import { buildDrawingPrimitives } from "../chart/drawingPrimitives";
import { drawCanvasPrimitives } from "../chart/drawCanvasPrimitives";
import type { DrawingQueryResult } from "../chart/DrawingViewportIndex";
import {
  DRAWING_DATA_FRAME_INTERVAL_MS,
  DRAWING_STATS_INTERVAL_MS,
  DRAWING_VIEWPORT_FRAME_INTERVAL_MS
} from "../chart/performanceLimits";
import type { VisibleTimeRangeNs } from "../chart/ChartAdapter";
import type { DrawingWorkerCommand, DrawingWorkerEvent } from "../lib/drawingProtocol";

export interface DrawingCanvasController {
  invalidate(): void;
  clear(): void;
}

export interface DrawingRenderStats {
  totalDrawings: number;
  matchedDrawings: number;
  renderedDrawings: number;
  primitiveCount: number;
  buildTimeMs: number;
}

interface Props {
  adapter: LightweightChartsAdapter;
  getDrawings: (range: VisibleTimeRangeNs | null) => DrawingQueryResult;
  getLatestTimeNs: () => number | null;
  tickSize: number;
  onStats?: (stats: DrawingRenderStats) => void;
}

type InvalidationMode = "data" | "viewport" | "content";

export const DrawingCanvasOverlay = forwardRef<DrawingCanvasController, Props>(
  function DrawingCanvasOverlay(
    { adapter, getDrawings, getLatestTimeNs, tickSize, onStats },
    forwardedRef
  ) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const [rendererGeneration, setRendererGeneration] = useState(0);
    const [forceMainThread, setForceMainThread] = useState(false);
    const adapterRef = useRef(adapter);
    const getDrawingsRef = useRef(getDrawings);
    const getLatestTimeNsRef = useRef(getLatestTimeNs);
    const tickSizeRef = useRef(tickSize);
    const onStatsRef = useRef(onStats);
    const workerRef = useRef<Worker | null>(null);
    const workerReadyRef = useRef(false);
    const workerBusyRef = useRef(false);
    const dirtyRef = useRef(true);
    const pendingModeRef = useRef<InvalidationMode>("content");
    const frameRef = useRef<number | null>(null);
    const timerRef = useRef<number | null>(null);
    const scheduledForRef = useRef(Number.POSITIVE_INFINITY);
    const revisionRef = useRef(0);
    const lastDrawAtRef = useRef(0);
    const lastStatsAtRef = useRef(0);
    const sizeRef = useRef({ width: 1, height: 1, devicePixelRatio: 1 });
    const contextRef = useRef<CanvasRenderingContext2D | null>(null);

    adapterRef.current = adapter;
    getDrawingsRef.current = getDrawings;
    getLatestTimeNsRef.current = getLatestTimeNs;
    tickSizeRef.current = tickSize;
    onStatsRef.current = onStats;

    const postWorker = (command: DrawingWorkerCommand, transfer: Transferable[] = []) => {
      workerRef.current?.postMessage(command, transfer);
    };

    const clearScheduledDraw = () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
      timerRef.current = null;
      frameRef.current = null;
      scheduledForRef.current = Number.POSITIVE_INFINITY;
    };

    const renderLatest = () => {
      if (!dirtyRef.current || workerBusyRef.current) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const { width, height } = sizeRef.current;
      if (width <= 1 || height <= 1) return;

      dirtyRef.current = false;
      pendingModeRef.current = "data";
      const startedAt = performance.now();
      const query = getDrawingsRef.current(adapterRef.current.visibleTimeRangeNs());
      const primitives = buildDrawingPrimitives(
        query.drawings,
        adapterRef.current.coordinates(),
        tickSizeRef.current,
        width,
        height,
        getLatestTimeNsRef.current()
      );
      const finishedAt = performance.now();
      lastDrawAtRef.current = finishedAt;
      revisionRef.current += 1;

      const statsHandler = onStatsRef.current;
      if (statsHandler && finishedAt - lastStatsAtRef.current >= DRAWING_STATS_INTERVAL_MS) {
        lastStatsAtRef.current = finishedAt;
        statsHandler({
          totalDrawings: query.totalCount,
          matchedDrawings: query.matchedCount,
          renderedDrawings: query.drawings.length,
          primitiveCount: primitives.length,
          buildTimeMs: finishedAt - startedAt
        });
      }

      if (workerRef.current && workerReadyRef.current) {
        workerBusyRef.current = true;
        postWorker({
          type: "draw",
          revision: revisionRef.current,
          primitives
        });
        return;
      }

      const context = contextRef.current;
      if (context) drawCanvasPrimitives(context, primitives, width, height);
    };

    const scheduleDraw = (mode: InvalidationMode = "content") => {
      dirtyRef.current = true;
      if (invalidationPriority(mode) > invalidationPriority(pendingModeRef.current)) {
        pendingModeRef.current = mode;
      }
      if (workerBusyRef.current) return;

      const now = performance.now();
      const interval = invalidationInterval(pendingModeRef.current);
      const target = pendingModeRef.current === "content"
        ? now
        : Math.max(now, lastDrawAtRef.current + interval);
      if (scheduledForRef.current <= target) return;

      clearScheduledDraw();
      scheduledForRef.current = target;
      const launch = () => {
        timerRef.current = null;
        frameRef.current = window.requestAnimationFrame(() => {
          frameRef.current = null;
          scheduledForRef.current = Number.POSITIVE_INFINITY;
          renderLatest();
        });
      };
      const delay = Math.max(0, target - now);
      if (delay <= 1) launch();
      else timerRef.current = window.setTimeout(launch, delay);
    };

    const clear = () => {
      clearScheduledDraw();
      dirtyRef.current = false;
      if (workerRef.current && workerReadyRef.current) {
        postWorker({ type: "clear" });
      } else {
        const context = contextRef.current;
        const { width, height } = sizeRef.current;
        context?.clearRect(0, 0, width, height);
      }
    };

    useImperativeHandle(forwardedRef, () => ({
      invalidate: () => scheduleDraw("content"),
      clear
    }));

    useEffect(() => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      let worker: Worker | null = null;
      let recovering = false;
      const fallBackToMainThread = (detail: string) => {
        if (recovering) return;
        recovering = true;
        console.warn("Drawing worker unavailable; switching to main-thread rendering", detail);
        workerBusyRef.current = false;
        workerReadyRef.current = false;
        setForceMainThread(true);
        setRendererGeneration(value => value + 1);
      };
      const canUseOffscreen =
        !forceMainThread &&
        typeof Worker !== "undefined" &&
        "transferControlToOffscreen" in canvas;

      if (canUseOffscreen) {
        try {
          const offscreen = canvas.transferControlToOffscreen();
          worker = new Worker(
            new URL("../workers/drawing.worker.ts", import.meta.url),
            { type: "module", name: "vex-drawing-renderer" }
          );
          workerRef.current = worker;
          worker.onmessage = event => {
            const message = event.data as DrawingWorkerEvent;
            if (message.type === "ready") {
              workerReadyRef.current = true;
              scheduleDraw("content");
              return;
            }
            if (message.type === "drawn") {
              workerBusyRef.current = false;
              if (dirtyRef.current) scheduleDraw(pendingModeRef.current);
              return;
            }
            fallBackToMainThread(message.detail);
          };
          worker.onerror = event => {
            fallBackToMainThread(event.message);
          };
          const { width, height, devicePixelRatio } = sizeRef.current;
          postWorker(
            { type: "initialize", canvas: offscreen, width, height, devicePixelRatio },
            [offscreen]
          );
        } catch (error) {
          fallBackToMainThread(error instanceof Error ? error.message : String(error));
          return () => {
            worker?.terminate();
            workerRef.current = null;
            workerReadyRef.current = false;
            workerBusyRef.current = false;
          };
        }
      } else {
        contextRef.current = canvas.getContext("2d", { alpha: true, desynchronized: true });
      }

      const resize = () => {
        const rect = canvas.getBoundingClientRect();
        const width = Math.max(1, Math.floor(rect.width));
        const height = Math.max(1, Math.floor(rect.height));
        const devicePixelRatio = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
        sizeRef.current = { width, height, devicePixelRatio };

        if (workerRef.current) {
          postWorker({ type: "resize", width, height, devicePixelRatio });
        } else {
          canvas.width = Math.floor(width * devicePixelRatio);
          canvas.height = Math.floor(height * devicePixelRatio);
          canvas.style.width = `${width}px`;
          canvas.style.height = `${height}px`;
          contextRef.current?.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
        }
        scheduleDraw("viewport");
      };

      const resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(canvas);
      resize();
      scheduleDraw("content");

      return () => {
        resizeObserver.disconnect();
        clearScheduledDraw();
        worker?.terminate();
        workerRef.current = null;
        workerReadyRef.current = false;
        workerBusyRef.current = false;
        contextRef.current = null;
      };
    }, [forceMainThread, rendererGeneration]);

    useEffect(() => {
      adapterRef.current = adapter;
      const unsubscribe = adapter.subscribeRender(reason => {
        scheduleDraw(reason === "data" ? "data" : reason === "strategy" ? "content" : "viewport");
      });
      scheduleDraw("content");
      return unsubscribe;
    }, [adapter]);

    useEffect(() => {
      getDrawingsRef.current = getDrawings;
      getLatestTimeNsRef.current = getLatestTimeNs;
      tickSizeRef.current = tickSize;
      scheduleDraw("content");
    }, [getDrawings, getLatestTimeNs, tickSize]);

    return (
      <canvas
        key={rendererGeneration}
        ref={canvasRef}
        className="drawing-canvas-overlay"
        aria-hidden="true"
      />
    );
  }
);

function invalidationInterval(mode: InvalidationMode): number {
  if (mode === "data") return DRAWING_DATA_FRAME_INTERVAL_MS;
  if (mode === "viewport") return DRAWING_VIEWPORT_FRAME_INTERVAL_MS;
  return 0;
}

function invalidationPriority(mode: InvalidationMode): number {
  if (mode === "content") return 3;
  if (mode === "viewport") return 2;
  return 1;
}
