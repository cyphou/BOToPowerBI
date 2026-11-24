import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from powerbi_import.progress import MigrationProgress, NullProgress


class MigrationProgressTests(unittest.TestCase):
    def test_callback_step_complete_fail_skip_summary(self):
        events = []
        progress = MigrationProgress(total_steps=4, on_step=lambda *args: events.append(args), show_bar=False)
        progress.start("Extract")
        progress.complete("12 tables")
        progress.start("Convert")
        progress.fail("bad formula")
        progress.skip("Deploy", "not authorized")

        self.assertEqual([event[2] for event in events], ["in_progress", "complete", "in_progress", "failed", "skipped"])
        summary = progress.summary()
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(len(summary["steps"]), 3)
        self.assertEqual(summary["steps"][0]["message"], "12 tables")
        self.assertEqual(summary["steps"][1]["error"], "bad formula")

    def test_complete_fail_and_skip_without_started_steps_are_safe(self):
        progress = MigrationProgress(show_bar=False)
        progress.complete("ignored")
        progress.fail("ignored")
        progress.skip("Validation", "synthetic")
        self.assertEqual(progress.summary()["skipped"], 1)

    def test_progress_bar_status_icons_and_messages(self):
        progress = MigrationProgress(total_steps=2, show_bar=True, bar_width=4)
        with patch("powerbi_import.progress.time.time", side_effect=[100.0, 100.25, 101.0, 102.0]):
            output = io.StringIO()
            with redirect_stderr(output):
                progress.start("Extract")
                progress.complete("done")
                progress.start("Generate")
                progress.fail("error")
        text = output.getvalue()
        self.assertIn("⏳", text)
        self.assertIn("✅", text)
        self.assertIn("❌", text)
        self.assertIn("done", text)
        self.assertIn("error", text)
        self.assertIn("1/2", text)
        self.assertIn("2/2", text)

    def test_skip_bar_and_unknown_status_icon(self):
        progress = MigrationProgress(total_steps=0, show_bar=False)
        progress._print_bar("Step", "unknown", "message")
        progress.show_bar = True
        progress.bar_width = 2
        output = io.StringIO()
        with redirect_stderr(output):
            progress.skip("Optional", "no source")
        self.assertIn("⏭️", output.getvalue())
        self.assertIn("no source", output.getvalue())

    def test_null_progress_and_summary(self):
        null = NullProgress()
        null.start("step")
        null.complete("done")
        null.fail("error")
        null.skip("other", "reason")
        self.assertEqual(null.summary(), {"steps": [], "total_elapsed": 0, "completed": 0, "failed": 0, "skipped": 0})


if __name__ == "__main__":
    unittest.main()
