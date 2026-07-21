from dataclasses import dataclass
from decimal import Decimal

from vex_contracts.replay import ReplayBootstrap, ReplayFrame
from vex_contracts.timeframes import Timeframe
from vex_replay.repository import ReplayRunRepository


@dataclass(slots=True)
class ReplaySession:
    repository: ReplayRunRepository
    run_id: str
    symbol: str
    timeframe: Timeframe
    cursor_sequence: int
    cursor_time_ns: int
    playing: bool = False
    speed: Decimal = Decimal("1")

    @classmethod
    def create(
        cls,
        repository: ReplayRunRepository,
        run_id: str,
        symbol: str | None = None,
        timeframe: Timeframe | None = None,
    ) -> tuple["ReplaySession", ReplayBootstrap]:
        bootstrap = repository.bootstrap(run_id, symbol, timeframe)
        return (
            cls(
                repository=repository,
                run_id=run_id,
                symbol=bootstrap.symbol,
                timeframe=bootstrap.timeframe,
                cursor_sequence=bootstrap.cursor_sequence,
                cursor_time_ns=bootstrap.cursor_time_ns,
            ),
            bootstrap,
        )

    def play(self) -> ReplayFrame:
        self.playing = True
        return self.state_frame()

    def pause(self) -> ReplayFrame:
        self.playing = False
        return self.state_frame()

    def set_speed(self, speed: Decimal) -> ReplayFrame:
        if speed <= 0 or speed > Decimal("100000"):
            raise ValueError("speed must be greater than zero and at most 100000")
        self.speed = speed
        return self.state_frame()

    def set_timeframe(self, timeframe: Timeframe) -> ReplayBootstrap:
        descriptor = self.repository.descriptor(self.run_id)
        if timeframe not in descriptor.available_timeframes:
            raise ValueError(f"timeframe is not available: {timeframe.value}")
        self.timeframe = timeframe
        return self.repository.bootstrap(
            self.run_id,
            self.symbol,
            self.timeframe,
            self.cursor_time_ns,
        )

    def reset(self) -> ReplayBootstrap:
        bootstrap = self.repository.bootstrap(self.run_id, self.symbol, self.timeframe)
        self.cursor_sequence = bootstrap.cursor_sequence
        self.cursor_time_ns = bootstrap.cursor_time_ns
        self.playing = False
        return bootstrap

    def seek_time(self, time_ns: int) -> ReplayBootstrap:
        bootstrap = self.repository.bootstrap(
            self.run_id,
            self.symbol,
            self.timeframe,
            time_ns,
        )
        self.cursor_sequence = bootstrap.cursor_sequence
        self.cursor_time_ns = bootstrap.cursor_time_ns
        return bootstrap

    def seek_progress(self, progress: Decimal) -> ReplayBootstrap:
        if progress < 0 or progress > 1:
            raise ValueError("progress must be between zero and one")
        descriptor = self.repository.descriptor(self.run_id)
        target = descriptor.start_time_ns + int(
            Decimal(descriptor.end_time_ns - descriptor.start_time_ns) * progress
        )
        return self.seek_time(target)

    def step_forward(self, count: int = 1) -> ReplayFrame:
        if count <= 0:
            raise ValueError("count must be positive")
        bars = self.repository.execution_bars_after(self.run_id, self.cursor_sequence, count)
        if not bars:
            self.playing = False
            return ReplayFrame(
                frame_type="completed",
                cursor_sequence=self.cursor_sequence,
                cursor_time_ns=self.cursor_time_ns,
                progress=Decimal("1"),
                playing=False,
                speed=self.speed,
                account=self.repository.account_at(self.run_id, self.cursor_time_ns),
            )
        previous_time = self.cursor_time_ns
        final_bar = bars[-1]
        self.cursor_sequence = final_bar.sequence
        self.cursor_time_ns = final_bar.close_time_ns
        visible_bars = self.repository.bars_for_view(
            self.run_id,
            self.symbol,
            self.timeframe,
            previous_time,
            self.cursor_time_ns,
        )
        timeline = self.repository.timeline_between(
            self.run_id,
            previous_time,
            self.cursor_time_ns,
        )
        return ReplayFrame(
            frame_type="advance",
            cursor_sequence=self.cursor_sequence,
            cursor_time_ns=self.cursor_time_ns,
            progress=self.repository.progress(self.run_id, self.cursor_time_ns),
            playing=self.playing,
            speed=self.speed,
            bars=visible_bars,
            timeline=timeline,
            account=self.repository.account_at(self.run_id, self.cursor_time_ns),
        )

    def step_backward(self) -> ReplayBootstrap:
        previous = self.repository.execution_bar_before(self.run_id, self.cursor_sequence)
        if previous is None:
            return self.reset()
        return self.seek_time(previous.close_time_ns)

    def state_frame(self) -> ReplayFrame:
        return ReplayFrame(
            frame_type="state",
            cursor_sequence=self.cursor_sequence,
            cursor_time_ns=self.cursor_time_ns,
            progress=self.repository.progress(self.run_id, self.cursor_time_ns),
            playing=self.playing,
            speed=self.speed,
            account=self.repository.account_at(self.run_id, self.cursor_time_ns),
        )
