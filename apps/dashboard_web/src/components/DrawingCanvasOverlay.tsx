import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef
} from "react";
import type { LightweightChartsAdapter } from "../chart/LightweightChartsAdapter";
import { buildDrawingPrimitives } from "../chart/drawingPrimitives";
import { drawCanvasPrimitives } from "../chart/drawCanvasPrimitives";
import type { DrawingState } from "../chart/chartState";
import type { DrawingWorkerCommand, DrawingWorkerEvent } from "../lib/drawingProtocol";

export interface DrawingCanvasController {
  invalidate(): void;
  clear(): void;
}

interface Props {
  adapter: LightweightChartsAdapter;
  getDrawings: () => Iterable<DrawingState>;
  tickSize: number;
}

export const DrawingCanvasOverlay = forwardRef<DrawingCanvasController, Props>(
  function DrawingCanvasOverlay({ adapter, getDrawings, tickSize }, forwardedRef) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const adapterRef = useRef(adapter);
    const getDrawingsRef = useRef(getDrawings);
    const tickSizeRef = useRef(tickSize);
    const workerRef = useRef<Worker | null>(null);
    const workerReadyRef = useRef(false);
    const workerBusyRef = useRef(false);
    const dirtyRef = useRef(true);
    const frameRef = useRef<number | null>(null);
    const revisionRef = useRef(0);
    const sizeRef = useRef({ width: 1, height: 1, devicePixelRatio: 1 });
    const contextRef = useRef<CanvasRenderingContext2D | null>(null);

    adapterRef.current = adapter;
    getDrawingsRef.current = getDrawings;
    tickSizeRef.current = tickSize;

    const postWorker = (command: DrawingWorkerCommand, transfer: Transferable[] = []) => {
      workerRef.current?.postMessage(command, transfer);
    };

    const renderLatest = () => {
      if (!dirtyRef.current || workerBusyRef.current) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const { width, height } = sizeRef.current;
      if (width <= 1 || height <= 1) return;

      dirtyRef.current = false;
      const primitives = buildDrawingPrimitives(
        getDrawingsRef.current(),
        adapterRef.current.coordinates(),
        tickSizeRef.current,
        width,
        height
      );
      revisionRef.current += 1;

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

    const scheduleDraw = () => {
      dirtyRef.current = true;
      if (frameRef.current !== null) return;
      frameRef.current = window.requestAnimationFrame(() => {
        frameRef.current = null;
        renderLatest();
      });
    };

    const clear = () => {
      dirtyRef.current = false;
      if (workerRef.current && workerReadyRef.current) {
        postWorker({ type: "clear" });
      } else {
        const context = contextRef.current;
        const { width, height } = sizeRef.current;
        context?.clearRect(0, 0, width, height);
      }
    };

    useImperativeHandle(forwardedRef, () => ({ invalidate: scheduleDraw, clear }));

    useEffect(() => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      let worker: Worker | null = null;
      const canUseOffscreen =
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
              scheduleDraw();
              return;
            }
            if (message.type === "drawn") {
              workerBusyRef.current = false;
              if (dirtyRef.current) scheduleDraw();
              return;
            }
            console.error("Drawing worker failed", message.detail);
            workerBusyRef.current = false;
          };
          worker.onerror = event => {
            console.error("Drawing worker crashed", event.message);
            workerBusyRef.current = false;
          };
          const { width, height, devicePixelRatio } = sizeRef.current;
          postWorker(
            { type: "initialize", canvas: offscreen, width, height, devicePixelRatio },
            [offscreen]
          );
        } catch (error) {
          console.warn("Offscreen drawing renderer unavailable, using main-thread canvas", error);
          workerRef.current = null;
          contextRef.current = canvas.getContext("2d", { alpha: true, desynchronized: true });
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
        scheduleDraw();
      };

      const resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(canvas);
      resize();
      scheduleDraw();

      return () => {
        resizeObserver.disconnect();
        if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
        worker?.terminate();
        workerRef.current = null;
        workerReadyRef.current = false;
        workerBusyRef.current = false;
        contextRef.current = null;
      };
    }, []);

    useEffect(() => {
      adapterRef.current = adapter;
      const unsubscribe = adapter.subscribeRender(scheduleDraw);
      scheduleDraw();
      return unsubscribe;
    }, [adapter]);

    useEffect(() => {
      getDrawingsRef.current = getDrawings;
      tickSizeRef.current = tickSize;
      scheduleDraw();
    }, [getDrawings, tickSize]);

    return <canvas ref={canvasRef} className="drawing-canvas-overlay" aria-hidden="true" />;
  }
);
