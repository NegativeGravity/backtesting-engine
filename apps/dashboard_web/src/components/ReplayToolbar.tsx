import { memo } from "react";
import {
  Clock3,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward
} from "lucide-react";
import { formatDateTime } from "../lib/format";

interface Props {
  playing: boolean;
  speed: number;
  progress: number;
  cursorTimeNs: number;
  onPlayPause: () => void;
  onStepBack: () => void;
  onStepForward: () => void;
  onReset: () => void;
  onSpeedChange: (speed: number) => void;
  onSeek: (progress: number) => void;
}

const speeds = [1, 2, 5, 10, 25, 50, 100, 250];

export const ReplayToolbar = memo(function ReplayToolbar({
  playing,
  speed,
  progress,
  cursorTimeNs,
  onPlayPause,
  onStepBack,
  onStepForward,
  onReset,
  onSpeedChange,
  onSeek
}: Props) {
  const percent = Math.max(0, Math.min(100, progress * 100));
  return (
    <div className={`replay-toolbar ${playing ? "is-playing" : ""}`}>
      <div className="transport-controls">
        <button className="transport-button" onClick={onReset} title="Reset replay (R)"><RotateCcw size={15} /></button>
        <button className="transport-button" onClick={onStepBack} title="Previous candle (←)"><SkipBack size={16} /></button>
        <button className="play-button" onClick={onPlayPause} title={playing ? "Pause (Space)" : "Play (Space)"}>
          {playing ? <Pause size={17} /> : <Play size={17} fill="currentColor" />}
        </button>
        <button className="transport-button" onClick={onStepForward} title="Next candle (→)"><SkipForward size={16} /></button>
      </div>

      <label className="speed-select">
        <span>Replay</span>
        <select value={speed} onChange={event => onSpeedChange(Number(event.target.value))}>
          {speeds.map(item => <option key={item} value={item}>{item} bars/s</option>)}
        </select>
      </label>

      <div className="timeline-stack">
        <div className="timeline-meta">
          <span>Progress</span>
          <strong>{percent.toFixed(2)}%</strong>
        </div>
        <div className="timeline-control">
          <div className="timeline-track" />
          <div className="timeline-progress" style={{ width: `${percent}%` }} />
          <input
            aria-label="Replay progress"
            type="range"
            min="0"
            max="10000"
            value={Math.round(progress * 10000)}
            onChange={event => onSeek(Number(event.target.value) / 10000)}
          />
        </div>
      </div>

      <div className="replay-time">
        <Clock3 size={14} />
        <div>
          <strong>{formatDateTime(cursorTimeNs)}</strong>
          <span>UTC · deterministic close-batch replay</span>
        </div>
      </div>
    </div>
  );
});
