"""Unit tests for the 60 FPS Side-by-Side Sliding Log Drawer animation and geometry in MainWindow."""

import math
import unittest
from unittest.mock import MagicMock, call, patch

from src.gui.main_window import MainWindow, COLORS


class TestDrawerAnimationMath(unittest.TestCase):
    """Tests verifying the ease-out cubic interpolation mathematics and bounds."""

    def test_ease_out_cubic_formula_and_bounds(self):
        """Verify ease-out cubic interpolation f(t) = 1 - (1 - t)^3."""
        def ease_out_cubic(t: float) -> float:
            return 1.0 - (1.0 - t) ** 3

        # Exact boundary values
        self.assertAlmostEqual(ease_out_cubic(0.0), 0.0, places=6)
        self.assertAlmostEqual(ease_out_cubic(1.0), 1.0, places=6)

        # Monotonicity check across fine increments
        prev = -1.0
        for i in range(101):
            t = i / 100.0
            val = ease_out_cubic(t)
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)
            self.assertGreater(val, prev)
            prev = val

        # Deceleration check: slope decreases as t approaches 1.0
        # Derivative: f'(t) = 3 * (1 - t)^2
        # At t=0, slope = 3.0 (instant tactile feedback)
        # At t=1, slope = 0.0 (smooth resting landing)
        slope_start = (ease_out_cubic(0.01) - ease_out_cubic(0.0)) / 0.01
        slope_end = (ease_out_cubic(1.0) - ease_out_cubic(0.99)) / 0.01
        self.assertAlmostEqual(slope_start, 3.0, delta=0.1)
        self.assertAlmostEqual(slope_end, 0.0, delta=0.05)
        self.assertGreater(slope_start, slope_end)

    def test_geometry_formulas(self):
        """Verify 55% / 44% + 1% gutter split formulas at discrete progress points."""
        def get_geometry(prog: float):
            hist_w = 1.0 - (0.45 * prog)
            log_relx = 1.0 - (0.44 * prog)
            log_w = 0.44
            return hist_w, log_relx, log_w

        # Closed state (prog = 0.0)
        hist_w_0, log_relx_0, log_w_0 = get_geometry(0.0)
        self.assertAlmostEqual(hist_w_0, 1.0, places=4)
        self.assertAlmostEqual(log_relx_0, 1.0, places=4)

        # Halfway state (prog = 0.5)
        hist_w_half, log_relx_half, _ = get_geometry(0.5)
        self.assertAlmostEqual(hist_w_half, 0.775, places=4)
        self.assertAlmostEqual(log_relx_half, 0.78, places=4)

        # Fully open state (prog = 1.0)
        hist_w_1, log_relx_1, log_w_1 = get_geometry(1.0)
        self.assertAlmostEqual(hist_w_1, 0.55, places=4)
        self.assertAlmostEqual(log_relx_1, 0.56, places=4)
        self.assertAlmostEqual(log_w_1, 0.44, places=4)

        # Gutter between history right edge (0.55) and drawer left edge (0.56) is exactly 0.01 (1%)
        gutter = log_relx_1 - hist_w_1
        self.assertAlmostEqual(gutter, 0.01, places=4)


class TestDrawerAnimationExecution(unittest.TestCase):
    """Tests verifying step-by-step execution, reversals, and safety."""

    def _create_mock_window(self):
        """Creates a mock MainWindow instance without Tk initialization."""
        win = object.__new__(MainWindow)
        win.winfo_exists = MagicMock(return_value=True)
        win.after = MagicMock(side_effect=lambda ms, cb: f"after_token_{cb}")
        win.after_cancel = MagicMock()
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

    def test_instant_open_and_close(self):
        """Verify non-animated instant toggle (animate=False)."""
        win = self._create_mock_window()

        # Instant open
        win._set_activity_log_visible(True, animate=False)
        self.assertTrue(win._log_drawer_visible)
        self.assertEqual(win._drawer_progress, 1.0)
        win.history_panel.place.assert_called_with(relx=0.0, rely=0.0, relwidth=0.55, relheight=1.0)
        win.connection_panel.place.assert_called_with(relx=0.56, rely=0.0, relwidth=0.44, relheight=1.0)
        win.connection_panel.lift.assert_called_once()
        win.log_drawer_btn.configure.assert_called_with(
            fg_color=COLORS["surface_alt"],
            border_color=COLORS["accent"],
        )

        # Instant close
        win.history_panel.place.reset_mock()
        win.connection_panel.place.reset_mock()
        win._set_activity_log_visible(False, animate=False)
        self.assertFalse(win._log_drawer_visible)
        self.assertEqual(win._drawer_progress, 0.0)
        win.connection_panel.place_forget.assert_called_once()
        win.history_panel.place.assert_called_with(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
        win.log_drawer_btn.configure.assert_called_with(
            fg_color=COLORS["input_bg"],
            border_color=COLORS["border"],
        )

    def test_animated_opening_all_11_steps(self):
        """Verify that opening runs through exactly 11 scheduled frames @ 16ms to 1.0 progress."""
        win = self._create_mock_window()

        scheduled_callbacks = []
        def mock_after(ms, cb):
            token = f"timer_{len(scheduled_callbacks) + 1}"
            scheduled_callbacks.append((ms, cb, token))
            return token

        def mock_after_cancel(token):
            scheduled_callbacks[:] = [item for item in scheduled_callbacks if item[2] != token]

        win.after = MagicMock(side_effect=mock_after)
        win.after_cancel = MagicMock(side_effect=mock_after_cancel)

        win._set_activity_log_visible(True, animate=True)
        self.assertTrue(win._log_drawer_visible)
        win.connection_panel.lift.assert_called_once()
        win.log_drawer_btn.configure.assert_called_with(
            fg_color=COLORS["surface_alt"],
            border_color=COLORS["accent"],
        )

        # Step 1 was executed synchronously inside _set_activity_log_visible
        # Now step through all remaining callbacks
        progress_history = [win._drawer_progress]
        step_count = 1

        while scheduled_callbacks:
            ms, cb, token = scheduled_callbacks.pop(0)
            self.assertEqual(ms, 16)
            cb()
            step_count += 1
            progress_history.append(win._drawer_progress)

        self.assertEqual(step_count, 11)
        self.assertEqual(len(progress_history), 11)
        self.assertAlmostEqual(win._drawer_progress, 1.0, places=5)
        self.assertIsNone(win._drawer_animation_id)

        # Verify final placement
        win.history_panel.place.assert_called_with(relx=0.0, rely=0.0, relwidth=0.55, relheight=1.0)
        win.connection_panel.place.assert_called_with(relx=0.56, rely=0.0, relwidth=0.44, relheight=1.0)

        # Verify progress monotonically increased
        for i in range(len(progress_history) - 1):
            self.assertLess(progress_history[i], progress_history[i + 1])

    def test_animated_closing_all_11_steps(self):
        """Verify that closing runs through exactly 11 scheduled frames @ 16ms down to 0.0."""
        win = self._create_mock_window()
        win._drawer_progress = 1.0
        win._log_drawer_visible = True

        scheduled_callbacks = []
        def mock_after(ms, cb):
            token = f"timer_{len(scheduled_callbacks) + 1}"
            scheduled_callbacks.append((ms, cb, token))
            return token

        def mock_after_cancel(token):
            scheduled_callbacks[:] = [item for item in scheduled_callbacks if item[2] != token]

        win.after = MagicMock(side_effect=mock_after)
        win.after_cancel = MagicMock(side_effect=mock_after_cancel)

        win._set_activity_log_visible(False, animate=True)
        self.assertFalse(win._log_drawer_visible)
        win.log_drawer_btn.configure.assert_called_with(
            fg_color=COLORS["input_bg"],
            border_color=COLORS["border"],
        )

        progress_history = [win._drawer_progress]
        step_count = 1

        while scheduled_callbacks:
            ms, cb, token = scheduled_callbacks.pop(0)
            self.assertEqual(ms, 16)
            cb()
            step_count += 1
            progress_history.append(win._drawer_progress)

        self.assertEqual(step_count, 11)
        self.assertAlmostEqual(win._drawer_progress, 0.0, places=5)
        self.assertIsNone(win._drawer_animation_id)

        # Verify final closed placement
        win.connection_panel.place_forget.assert_called()
        win.history_panel.place.assert_called_with(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)

        # Verify progress monotonically decreased
        for i in range(len(progress_history) - 1):
            self.assertGreater(progress_history[i], progress_history[i + 1])

    def test_midflight_reversal_open_to_close(self):
        """Verify clicking toggle mid-opening reverses smoothly from current progress."""
        win = self._create_mock_window()

        scheduled_callbacks = []
        def mock_after(ms, cb):
            token = f"timer_{len(scheduled_callbacks) + 1}"
            scheduled_callbacks.append((ms, cb, token))
            return token

        def mock_after_cancel(token):
            scheduled_callbacks[:] = [item for item in scheduled_callbacks if item[2] != token]

        win.after = MagicMock(side_effect=mock_after)
        win.after_cancel = MagicMock(side_effect=mock_after_cancel)

        # Start opening
        win._set_activity_log_visible(True, animate=True)
        # Advance 3 steps
        for _ in range(3):
            if scheduled_callbacks:
                ms, cb, token = scheduled_callbacks.pop(0)
                cb()

        mid_progress = win._drawer_progress
        self.assertGreater(mid_progress, 0.3)
        self.assertLess(mid_progress, 0.95)

        # Now user clicks toggle mid-flight to CLOSE
        win.toggle_activity_log()
        self.assertFalse(win._log_drawer_visible)

        # Step 1 of reversal executed immediately; progress should be moving towards 0.0
        reversal_step_1 = win._drawer_progress
        self.assertLess(reversal_step_1, mid_progress)

        # Drain reversal steps and verify monotonically decreasing to 0.0
        reversal_progress = [mid_progress, reversal_step_1]
        while scheduled_callbacks:
            ms, cb, token = scheduled_callbacks.pop(0)
            cb()
            reversal_progress.append(win._drawer_progress)

        for i in range(len(reversal_progress) - 1):
            self.assertGreater(reversal_progress[i], reversal_progress[i + 1])

        self.assertAlmostEqual(win._drawer_progress, 0.0, places=4)
        self.assertIsNone(win._drawer_animation_id)
        win.connection_panel.place_forget.assert_called()

    def test_midflight_reversal_close_to_open(self):
        """Verify clicking toggle mid-closing reverses smoothly back to open."""
        win = self._create_mock_window()
        win._drawer_progress = 1.0
        win._log_drawer_visible = True

        scheduled_callbacks = []
        def mock_after(ms, cb):
            token = f"timer_{len(scheduled_callbacks) + 1}"
            scheduled_callbacks.append((ms, cb, token))
            return token

        def mock_after_cancel(token):
            scheduled_callbacks[:] = [item for item in scheduled_callbacks if item[2] != token]

        win.after = MagicMock(side_effect=mock_after)
        win.after_cancel = MagicMock(side_effect=mock_after_cancel)

        # Start closing
        win._set_activity_log_visible(False, animate=True)
        # Advance 2 steps
        for _ in range(2):
            if scheduled_callbacks:
                ms, cb, token = scheduled_callbacks.pop(0)
                cb()

        mid_progress = win._drawer_progress
        self.assertGreater(mid_progress, 0.1)
        self.assertLess(mid_progress, 0.9)

        # Reverse back to OPEN mid-flight
        win.toggle_activity_log()
        self.assertTrue(win._log_drawer_visible)

        # Step 1 of reversal executed immediately; progress should be moving towards 1.0
        reversal_step_1 = win._drawer_progress
        self.assertGreater(reversal_step_1, mid_progress)

        # Drain reversal steps and verify monotonically increasing to 1.0
        reversal_progress = [mid_progress, reversal_step_1]
        while scheduled_callbacks:
            ms, cb, token = scheduled_callbacks.pop(0)
            cb()
            reversal_progress.append(win._drawer_progress)

        for i in range(len(reversal_progress) - 1):
            self.assertLess(reversal_progress[i], reversal_progress[i + 1])

        self.assertAlmostEqual(win._drawer_progress, 1.0, places=4)
        self.assertIsNone(win._drawer_animation_id)

    def test_rapid_successive_toggles(self):
        """Verify rapid multiple toggles without stutter, exception, or state desync."""
        win = self._create_mock_window()

        scheduled_callbacks = []
        def mock_after(ms, cb):
            token = f"timer_{len(scheduled_callbacks) + 1}"
            scheduled_callbacks.append((ms, cb, token))
            return token

        def mock_after_cancel(token):
            scheduled_callbacks[:] = [item for item in scheduled_callbacks if item[2] != token]

        win.after = MagicMock(side_effect=mock_after)
        win.after_cancel = MagicMock(side_effect=mock_after_cancel)

        # Toggle 6 times in rapid succession, executing 1 frame between each toggle
        for i in range(6):
            win.toggle_activity_log()
            if scheduled_callbacks:
                ms, cb, token = scheduled_callbacks.pop(0)
                cb()
            # Progress must always stay bounded in [0.0, 1.0]
            self.assertGreaterEqual(win._drawer_progress, 0.0)
            self.assertLessEqual(win._drawer_progress, 1.0)

        # Let the last animation finish
        while scheduled_callbacks:
            ms, cb, token = scheduled_callbacks.pop(0)
            cb()

        self.assertIsNone(win._drawer_animation_id)
        target = 1.0 if win._log_drawer_visible else 0.0
        self.assertAlmostEqual(win._drawer_progress, target, places=4)

    def test_winfo_exists_window_destroyed_safety(self):
        """Verify anim_step aborts cleanly if window is destroyed mid-animation."""
        win = self._create_mock_window()

        scheduled_callbacks = []
        def mock_after(ms, cb):
            scheduled_callbacks.append((ms, cb))
            return "timer_token"

        win.after = MagicMock(side_effect=mock_after)

        win._set_activity_log_visible(True, animate=True)
        self.assertEqual(len(scheduled_callbacks), 1)

        # Simulate window destruction
        win.winfo_exists = MagicMock(return_value=False)

        # Execute scheduled callback
        ms, cb = scheduled_callbacks.pop(0)
        # Should not raise exception
        cb()

        # Animation should have terminated without scheduling another after
        self.assertEqual(len(scheduled_callbacks), 0)
        self.assertIsNone(win._drawer_animation_id)

    def test_winfo_exists_panel_destroyed_safety(self):
        """Verify anim_step aborts cleanly if child panel is destroyed mid-animation."""
        win = self._create_mock_window()

        scheduled_callbacks = []
        def mock_after(ms, cb):
            scheduled_callbacks.append((ms, cb))
            return "timer_token"

        win.after = MagicMock(side_effect=mock_after)

        win._set_activity_log_visible(True, animate=True)
        self.assertEqual(len(scheduled_callbacks), 1)

        # Simulate history_panel destruction
        win.history_panel.winfo_exists = MagicMock(return_value=False)

        ms, cb = scheduled_callbacks.pop(0)
        cb()

        self.assertEqual(len(scheduled_callbacks), 0)
        self.assertIsNone(win._drawer_animation_id)

    def test_place_exception_handling_safety(self):
        """Verify anim_step handles place() raising TclError/Exception safely."""
        win = self._create_mock_window()
        win.history_panel.place.side_effect = RuntimeError("Tcl widget disappeared")

        scheduled_callbacks = []
        def mock_after(ms, cb):
            scheduled_callbacks.append((ms, cb))
            return "timer_token"

        win.after = MagicMock(side_effect=mock_after)

        # Should handle exception safely
        win._set_activity_log_visible(True, animate=True)
        self.assertIsNone(win._drawer_animation_id)

    def test_shutdown_cleans_drawer_animation_timer(self):
        """Verify shutdown cancels any running drawer animation timer."""
        win = self._create_mock_window()
        win._ui_dispatch_after_id = None
        win._search_timer = None
        win._session_state_after_id = None
        win._drawer_animation_id = "test_timer_123"
        win.destroy = MagicMock()

        win.shutdown()

        win.after_cancel.assert_called_with("test_timer_123")
        self.assertIsNone(win._drawer_animation_id)
        win.destroy.assert_called_once()

    def test_place_forget_called_when_prog_under_threshold(self):
        """Verify connection_panel.place_forget is called when progress <= 0.001."""
        win = self._create_mock_window()
        win._drawer_progress = 0.0005
        win._log_drawer_visible = False

        scheduled_callbacks = []
        def mock_after(ms, cb):
            scheduled_callbacks.append((ms, cb))
            return "timer_token"

        win.after = MagicMock(side_effect=mock_after)

        win._set_activity_log_visible(False, animate=True)
        win.connection_panel.place_forget.assert_called()


if __name__ == "__main__":
    unittest.main()
