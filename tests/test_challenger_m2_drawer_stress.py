"""Adversarial empirical stress testing for Milestone 2: 60 FPS Sliding Log Drawer.

Author: Challenger 1 (critic, specialist)
Validates:
- 100-cycle rapid toggle stress and stochastic fuzzing
- 10,000-cycle continuous mid-flight reversal float stability
- Sub-millisecond interrupts and mid-flight reversals
- Strict mathematical boundary invariants (0.0 <= prog <= 1.0, Wh + Wc <= 1.0, gutter >= 0)
- Multi-resolution integer pixel overlap verification (1024px to 4K)
- Timer queue integrity and leak prevention
- Widget lifecycle destruction, missing attributes, and error injection hardening
"""

import math
import random
import unittest
from unittest.mock import MagicMock, NonCallableMock, patch

from src.gui.main_window import MainWindow, COLORS


class TestDrawerMathematicalInvariants(unittest.TestCase):
    """Adversarial stress testing of mathematical formulas, geometry, and boundary invariants."""

    def test_ease_out_cubic_exhaustive_properties(self):
        """Property-based continuous stress test over 100,000 points."""
        def ease_out_cubic(t: float) -> float:
            return 1.0 - (1.0 - t) ** 3

        # Exact boundary values
        self.assertEqual(ease_out_cubic(0.0), 0.0)
        self.assertEqual(ease_out_cubic(1.0), 1.0)

        # Sampling 100,000 steps
        num_samples = 100_000
        prev_val = -1.0
        for i in range(num_samples + 1):
            t = i / num_samples
            val = ease_out_cubic(t)

            # Invariant 1: Range bounds [0.0, 1.0]
            self.assertGreaterEqual(val, 0.0, f"Failed at t={t}: val={val} < 0.0")
            self.assertLessEqual(val, 1.0, f"Failed at t={t}: val={val} > 1.0")

            # Invariant 2: Strict Monotonicity
            self.assertGreater(val, prev_val, f"Monotonicity violated at t={t}")
            prev_val = val

            # Invariant 3: Velocity f'(t) = 3*(1-t)^2 >= 0
            deriv = 3.0 * ((1.0 - t) ** 2)
            self.assertGreaterEqual(deriv, 0.0)

            # Invariant 4: Acceleration f''(t) = -6*(1-t) <= 0 (strictly decelerating / ease-out)
            accel = -6.0 * (1.0 - t)
            self.assertLessEqual(accel, 0.0)

    def test_geometry_envelope_and_gutter_invariants(self):
        """Stress test geometry layout constraints across 10,000 progress levels."""
        def compute_geometry(prog: float):
            hist_w = 1.0 - (0.45 * prog)
            log_relx = 1.0 - (0.44 * prog)
            log_w = 0.44
            return hist_w, log_relx, log_w

        num_samples = 10_000
        for i in range(num_samples + 1):
            prog = i / num_samples
            hist_w, log_relx, log_w = compute_geometry(prog)

            # Invariant 1: History width always stays within [0.55, 1.0]
            self.assertGreaterEqual(hist_w, 0.55 - 1e-9)
            self.assertLessEqual(hist_w, 1.0 + 1e-9)

            # Invariant 2: Log drawer relx always stays within [0.56, 1.0]
            self.assertGreaterEqual(log_relx, 0.56 - 1e-9)
            self.assertLessEqual(log_relx, 1.0 + 1e-9)

            # Invariant 3: No overlap / positive gutter between history right edge and log drawer left edge
            gutter = log_relx - hist_w
            self.assertGreaterEqual(gutter, -1e-9, f"Overlap detected at prog={prog}: gutter={gutter}")

            # At full open (prog=1.0), gutter must be exactly 0.01 (1%)
            if i == num_samples:
                self.assertAlmostEqual(gutter, 0.01, places=6)
                self.assertAlmostEqual(hist_w, 0.55, places=6)
                self.assertAlmostEqual(log_relx, 0.56, places=6)
                self.assertAlmostEqual(log_w, 0.44, places=6)

                # Invariant 4: Sum of widths Wh + Wc <= 1.0
                self.assertLessEqual(hist_w + log_w, 1.0 + 1e-9)
                self.assertAlmostEqual(hist_w + log_w, 0.99, places=6)

                # Invariant 5: Right boundary does not exceed container (log_relx + log_w <= 1.0)
                self.assertLessEqual(log_relx + log_w, 1.0 + 1e-9)
                self.assertAlmostEqual(log_relx + log_w, 1.00, places=6)

    def test_multi_resolution_pixel_grid_alignment(self):
        """Verify integer pixel boundaries across standard resolutions (1024px to 3840px 4K)."""
        resolutions = [1024, 1152, 1280, 1366, 1440, 1600, 1920, 2560, 3440, 3840]

        for width in resolutions:
            for i in range(101):
                prog = i / 100.0
                hist_w = 1.0 - (0.45 * prog)
                log_relx = 1.0 - (0.44 * prog)
                log_w = 0.44

                # Calculate pixel positions
                hist_px_right = int(round(width * hist_w))
                log_px_left = int(round(width * log_relx))

                # Gutter in pixels (always non-negative, preventing visual overlap)
                gutter_px = log_px_left - hist_px_right
                self.assertGreaterEqual(
                    gutter_px,
                    0,
                    f"Pixel collision at res {width}px, prog {prog}: hist_right={hist_px_right}, log_left={log_px_left}"
                )

                # At fully open position (prog = 1.0), right edge must dock exactly at width with 0px overflow
                if i == 100:
                    log_px_right = log_px_left + int(round(width * log_w))
                    self.assertLessEqual(
                        log_px_right,
                        width + 1,  # Allow 1px rounding tolerance
                        f"Right edge overflow at res {width}px, prog {prog}: log_right={log_px_right} > {width}"
                    )


class TestDrawerStressHarness(unittest.TestCase):
    """Adversarial stress harness with accurate timer tracking and event queue simulation."""

    def _create_harness_window(self):
        """Creates a mock MainWindow with strict timer queue tracking."""
        win = object.__new__(MainWindow)
        win.tk = NonCallableMock(spec=[])
        win.winfo_exists = MagicMock(return_value=True)

        win.active_timers = {}
        win._timer_counter = 0
        win.total_scheduled = 0
        win.total_cancelled = 0
        win.total_executed = 0

        def mock_after(ms, cb):
            win._timer_counter += 1
            token = f"timer_tok_{win._timer_counter}"
            win.active_timers[token] = (ms, cb)
            win.total_scheduled += 1
            return token

        def mock_after_cancel(token):
            if token in win.active_timers:
                del win.active_timers[token]
                win.total_cancelled += 1

        win.after = MagicMock(side_effect=mock_after)
        win.after_cancel = MagicMock(side_effect=mock_after_cancel)
        win.update_idletasks = MagicMock()

        win.history_panel = MagicMock()
        win.history_panel.winfo_exists = MagicMock(return_value=True)
        win.history_panel.place = MagicMock()

        win.connection_panel = MagicMock()
        win.connection_panel.winfo_exists = MagicMock(return_value=True)
        win.connection_panel.place = MagicMock()
        win.connection_panel.place_forget = MagicMock()
        win.connection_panel.lift = MagicMock()

        win.log_drawer_btn = MagicMock()
        win.log_drawer_btn.winfo_exists = MagicMock(return_value=True)
        win.log_drawer_btn.configure = MagicMock()

        win._drawer_animation_id = None
        win._log_drawer_visible = False
        win._drawer_progress = 0.0
        win._ui_dispatch_after_id = None
        win._search_timer = None
        win._session_state_after_id = None

        return win

    def _tick_single_timer(self, win):
        """Executes the next scheduled timer callback if one exists."""
        if not win.active_timers:
            return False
        # Pop the oldest active timer
        token = next(iter(win.active_timers.keys()))
        ms, cb = win.active_timers.pop(token)
        win.total_executed += 1
        cb()
        return True

    def _drain_all_timers(self, win, max_steps: int = 1000):
        """Drains all queued timers until empty or max_steps reached."""
        steps = 0
        while win.active_timers and steps < max_steps:
            self._tick_single_timer(win)
            steps += 1
        return steps

    def test_rapid_100_cycle_submillisecond_interrupts(self):
        """Stress: 100 consecutive rapid toggles with 0 delay (spam clicks before tick)."""
        win = self._create_harness_window()

        for cycle in range(1, 101):
            win.toggle_activity_log()
            # Assert only at most 1 active timer token in the system at any instant
            self.assertLessEqual(len(win.active_timers), 1, f"Timer leak at cycle {cycle}: {win.active_timers}")
            self.assertGreaterEqual(win._drawer_progress, 0.0)
            self.assertLessEqual(win._drawer_progress, 1.0)

        # Total scheduled minus cancelled minus executed must equal active_timers
        self.assertEqual(
            win.total_scheduled - win.total_cancelled - win.total_executed,
            len(win.active_timers)
        )

        # Drain the remaining animation for the final state
        steps = self._drain_all_timers(win)
        self.assertLessEqual(steps, 12)
        self.assertEqual(len(win.active_timers), 0)
        self.assertIsNone(win._drawer_animation_id)

        # Expected target state: 100 toggles starting from False -> ended at False (closed)
        self.assertFalse(win._log_drawer_visible)
        self.assertAlmostEqual(win._drawer_progress, 0.0, places=5)
        win.connection_panel.place_forget.assert_called()

    def test_continuous_10000_cycle_midflight_reversal_float_stability(self):
        """Stress: 10,000 rapid mid-flight reversals verifying floating point stability and bounds."""
        win = self._create_harness_window()
        rng = random.Random(1337)

        for cycle in range(1, 10_001):
            win.toggle_activity_log()

            # Execute 1 to 4 ticks mid-flight before reversing
            ticks = rng.randint(1, 4)
            for _ in range(ticks):
                if not self._tick_single_timer(win):
                    break

            # Invariant: Progress strictly bounded in [0.0, 1.0] without drift
            self.assertGreaterEqual(win._drawer_progress, 0.0)
            self.assertLessEqual(win._drawer_progress, 1.0)
            self.assertLessEqual(len(win.active_timers), 1)

        # Let the final animation resolve
        self._drain_all_timers(win)
        self.assertEqual(len(win.active_timers), 0)
        self.assertIsNone(win._drawer_animation_id)
        expected_target = 1.0 if win._log_drawer_visible else 0.0
        self.assertAlmostEqual(win._drawer_progress, expected_target, places=5)

    def test_stochastic_fuzzing_100_cycles(self):
        """Fuzz testing: 100 randomized cycles with arbitrary tick interruptions."""
        win = self._create_harness_window()
        rng = random.Random(42)  # Seed for reproducible adversarial fuzzing

        for cycle in range(1, 101):
            # Action 1: Toggle
            win.toggle_activity_log()
            self.assertLessEqual(len(win.active_timers), 1, f"Timer leak after toggle in cycle {cycle}")
            self.assertGreaterEqual(win._drawer_progress, 0.0)
            self.assertLessEqual(win._drawer_progress, 1.0)

            # Action 2: Advance random number of ticks [0 .. 15]
            ticks_to_advance = rng.randint(0, 15)
            for _ in range(ticks_to_advance):
                if not self._tick_single_timer(win):
                    break
                # Verify invariants after every single tick
                self.assertGreaterEqual(win._drawer_progress, 0.0)
                self.assertLessEqual(win._drawer_progress, 1.0)
                self.assertLessEqual(len(win.active_timers), 1)

        # Drain all remaining ticks
        self._drain_all_timers(win)
        self.assertEqual(len(win.active_timers), 0)
        self.assertIsNone(win._drawer_animation_id)

        # Verify final settled state is clean
        expected_target = 1.0 if win._log_drawer_visible else 0.0
        self.assertAlmostEqual(win._drawer_progress, expected_target, places=5)

    def test_interleaved_instant_and_animated_toggles(self):
        """Stress: calling _set_activity_log_visible(animate=False) while animation in flight."""
        win = self._create_harness_window()

        # Start animated open
        win._set_activity_log_visible(True, animate=True)
        # Advance 4 ticks
        for _ in range(4):
            self._tick_single_timer(win)

        self.assertGreater(win._drawer_progress, 0.4)
        self.assertLess(win._drawer_progress, 0.95)
        self.assertIsNotNone(win._drawer_animation_id)

        # Force immediate snap close (animate=False)
        win._set_activity_log_visible(False, animate=False)

        # Active timer must be immediately cancelled and wiped
        self.assertIsNone(win._drawer_animation_id)
        self.assertEqual(len(win.active_timers), 0)
        self.assertEqual(win._drawer_progress, 0.0)
        self.assertFalse(win._log_drawer_visible)
        win.connection_panel.place_forget.assert_called()
        win.history_panel.place.assert_called_with(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)

        # Verify no stale callbacks remain
        self.assertFalse(self._tick_single_timer(win))

    def test_idempotent_visibility_calls_no_op(self):
        """Stress: requesting same visibility state repeatedly when already at rest."""
        win = self._create_harness_window()

        # When closed at rest, setting False should be instant no-op
        self.assertEqual(win._drawer_progress, 0.0)
        self.assertFalse(win._log_drawer_visible)

        win._set_activity_log_visible(False, animate=True)
        self.assertEqual(len(win.active_timers), 0)
        self.assertIsNone(win._drawer_animation_id)
        self.assertEqual(win._drawer_progress, 0.0)

        # Now open fully
        win._set_activity_log_visible(True, animate=False)
        self.assertEqual(win._drawer_progress, 1.0)
        self.assertTrue(win._log_drawer_visible)

        # Setting True again when already open at 1.0 should be instant no-op
        win._set_activity_log_visible(True, animate=True)
        self.assertEqual(len(win.active_timers), 0)
        self.assertIsNone(win._drawer_animation_id)
        self.assertEqual(win._drawer_progress, 1.0)

    def test_widget_destruction_during_all_animation_steps(self):
        """Adversarial test: destroying window or panels at every individual step [0..11]."""
        for kill_step in range(12):
            for target in ["window", "history_panel", "connection_panel"]:
                win = self._create_harness_window()
                win._set_activity_log_visible(True, animate=True)

                for step in range(kill_step):
                    if not self._tick_single_timer(win):
                        break

                # Inject destruction
                if target == "window":
                    win.winfo_exists = MagicMock(return_value=False)
                elif target == "history_panel":
                    win.history_panel.winfo_exists = MagicMock(return_value=False)
                elif target == "connection_panel":
                    win.connection_panel.winfo_exists = MagicMock(return_value=False)

                # Next tick should handle gracefully without uncaught exception
                if win.active_timers:
                    self._tick_single_timer(win)

                # Animation ID must be cleared and no new timer scheduled
                self.assertIsNone(win._drawer_animation_id)
                self.assertEqual(len(win.active_timers), 0)

    def test_place_exception_fault_injection(self):
        """Stress: inject unexpected runtime exception during widget place."""
        win = self._create_harness_window()

        # Start animation
        win._set_activity_log_visible(True, animate=True)

        # Inject exception in history_panel.place
        win.history_panel.place.side_effect = RuntimeError("Simulated Tk place layout error")

        # Execute next tick
        self.assertTrue(self._tick_single_timer(win))

        # Must gracefully abort without unhandled exception and clear timer
        self.assertIsNone(win._drawer_animation_id)
        self.assertEqual(len(win.active_timers), 0)

    def test_after_cancel_exception_safety(self):
        """Stress: after_cancel raising exception should not crash toggle."""
        win = self._create_harness_window()
        win.after_cancel.side_effect = RuntimeError("Tcl error in after_cancel")

        win._drawer_animation_id = "stale_token"
        win._log_drawer_visible = False

        # Should not raise exception
        win.toggle_activity_log()
        self.assertTrue(win._log_drawer_visible)

    def test_shutdown_with_active_animation_stress(self):
        """Stress: shutdown called at arbitrary in-flight animation frames."""
        for step_to_stop in [1, 3, 5, 8]:
            win = self._create_harness_window()
            win.destroy = MagicMock()

            win._set_activity_log_visible(True, animate=True)
            for _ in range(step_to_stop):
                self._tick_single_timer(win)

            self.assertIsNotNone(win._drawer_animation_id)
            win.shutdown()

            self.assertIsNone(win._drawer_animation_id)
            self.assertEqual(len(win.active_timers), 0)
            win.destroy.assert_called_once()

    def test_missing_panels_graceful_no_op(self):
        """Stress: calling toggle when panels are not yet initialized or deleted."""
        win = self._create_harness_window()
        del win.connection_panel
        del win.history_panel

        # Neither history_panel nor connection_panel exists
        win.toggle_activity_log()
        # Should gracefully return without throwing AttributeError
        self.assertIsNone(win._drawer_animation_id)

    def test_log_drawer_btn_color_theme_integrity(self):
        """Verify button styling matches exact design tokens across all transitions."""
        win = self._create_harness_window()

        # Initial state: closed
        self.assertFalse(win._log_drawer_visible)

        # Open
        win.toggle_activity_log()
        win.log_drawer_btn.configure.assert_called_with(
            fg_color=COLORS["surface_alt"],
            border_color=COLORS["accent"],
        )

        # Close
        win.toggle_activity_log()
        win.log_drawer_btn.configure.assert_called_with(
            fg_color=COLORS["input_bg"],
            border_color=COLORS["border"],
        )


if __name__ == "__main__":
    unittest.main()
