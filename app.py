"""
Local Contractors — GUI launcher
Requires: PyQt5   (pip install PyQt5)
"""

import sys
import subprocess
import shlex
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QCheckBox, QComboBox, QSpinBox,
    QDoubleSpinBox, QPushButton, QTextEdit, QFileDialog,
    QGroupBox, QScrollArea, QSizePolicy, QFrame,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QProcess
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette

# ── colour palette ───────────────────────────────────────────────
BG       = "#1e1e1e"
PANEL    = "#252526"
BORDER   = "#3c3c3c"
TEXT     = "#d4d4d4"
LABEL    = "#9cdcfe"
ACCENT   = "#0e639c"
ACCENT_H = "#1177bb"
GREEN    = "#4ec9b0"
RED      = "#f44747"
MONO     = "Consolas, 'Courier New', monospace"

BASE_SS = f"""
QMainWindow, QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {PANEL};
}}
QTabBar::tab {{
    background: {BG};
    color: {TEXT};
    padding: 6px 18px;
    border: 1px solid {BORDER};
    border-bottom: none;
}}
QTabBar::tab:selected {{
    background: {PANEL};
    color: #ffffff;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 6px;
    font-size: 12px;
    color: {LABEL};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    top: -1px;
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 3px 6px;
    color: {TEXT};
    min-height: 22px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: {PANEL};
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QCheckBox {{
    spacing: 6px;
    color: {TEXT};
}}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {BG};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QPushButton {{
    background: {ACCENT};
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 6px 18px;
    min-width: 90px;
}}
QPushButton:hover  {{ background: {ACCENT_H}; }}
QPushButton:pressed {{ background: #0a4f7a; }}
QPushButton#stop  {{ background: #6e3030; }}
QPushButton#stop:hover {{ background: {RED}; }}
QTextEdit {{
    background: #0d0d0d;
    color: #cccccc;
    font-family: {MONO};
    font-size: 12px;
    border: 1px solid {BORDER};
}}
QScrollArea {{ border: none; }}
QLabel#section {{ color: {LABEL}; font-size: 11px; font-weight: bold; }}
QFrame#sep {{
    background: {BORDER};
    max-height: 1px;
    min-height: 1px;
}}
"""

NICHES = [
    "Imbianchino / Pittore edile",
    "Idraulico / Termoidraulico",
    "Elettricista",
    "Toelettatore",
    "Giardiniere",
    "Falegname",
    "Piastrellista",
    "Muratore / Ristrutturazioni",
    "Fabbro",
    "Carrozziere",
    "Plumber",
    "Dog Groomer",
    "Phone Repair",
    "Auto Detailer",
    "Landscaper",
]


# ── subprocess runner ────────────────────────────────────────────
class Runner(QThread):
    line_out = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd
        self._proc = None

    def run(self):
        self._proc = subprocess.Popen(
            self.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in self._proc.stdout:
            self.line_out.emit(line.rstrip())
        self._proc.wait()
        self.finished.emit(self._proc.returncode)

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()


# ── niche checkbox grid ──────────────────────────────────────────
class NicheSelector(QGroupBox):
    def __init__(self):
        super().__init__("Niches / Nicchie")
        grid = QGridLayout()
        grid.setSpacing(4)
        self.boxes = {}
        cols = 3
        for i, n in enumerate(NICHES):
            cb = QCheckBox(n)
            grid.addWidget(cb, i // cols, i % cols)
            self.boxes[n] = cb
        self.setLayout(grid)

    def selected(self):
        return [n for n, cb in self.boxes.items() if cb.isChecked()]


# ── shared params widget ─────────────────────────────────────────
def sep():
    f = QFrame()
    f.setObjectName("sep")
    return f


def lbl(text):
    l = QLabel(text)
    return l


def section_label(text):
    l = QLabel(text)
    l.setObjectName("section")
    return l


class CommonParams(QWidget):
    """Params shared by both Run and Batch tabs."""

    def __init__(self):
        super().__init__()
        g = QGridLayout()
        g.setVerticalSpacing(6)
        g.setHorizontalSpacing(12)
        g.setColumnMinimumWidth(1, 140)
        g.setColumnMinimumWidth(3, 140)

        row = 0
        g.addWidget(section_label("Filters"), row, 0, 1, 4); row += 1

        g.addWidget(lbl("Min reviews"), row, 0)
        self.min_reviews = QSpinBox(); self.min_reviews.setRange(0, 9999); self.min_reviews.setValue(1)
        g.addWidget(self.min_reviews, row, 1)

        g.addWidget(lbl("Max reviews"), row, 2)
        self.max_reviews = QSpinBox(); self.max_reviews.setRange(0, 9999); self.max_reviews.setValue(15)
        g.addWidget(self.max_reviews, row, 3); row += 1

        g.addWidget(sep(), row, 0, 1, 4); row += 1
        g.addWidget(section_label("Scraper"), row, 0, 1, 4); row += 1

        g.addWidget(lbl("Scroll times"), row, 0)
        self.scroll_times = QSpinBox(); self.scroll_times.setRange(1, 999); self.scroll_times.setValue(30)
        g.addWidget(self.scroll_times, row, 1)

        g.addWidget(lbl("Max results"), row, 2)
        self.max_results = QSpinBox(); self.max_results.setRange(0, 999); self.max_results.setValue(20)
        self.max_results.setSpecialValueText("auto")
        g.addWidget(self.max_results, row, 3); row += 1

        g.addWidget(lbl("Language"), row, 0)
        self.lang = QComboBox(); self.lang.addItems(["en", "it"])
        g.addWidget(self.lang, row, 1)

        g.addWidget(lbl("Log level"), row, 2)
        self.log_level = QComboBox(); self.log_level.addItems(["INFO", "DEBUG", "WARNING", "ERROR"])
        g.addWidget(self.log_level, row, 3); row += 1

        g.addWidget(sep(), row, 0, 1, 4); row += 1
        g.addWidget(section_label("Options"), row, 0, 1, 4); row += 1

        self.headless       = QCheckBox("Headless browser")
        self.no_http_check  = QCheckBox("Skip HTTP check  (--no-http-check)")
        self.debug_screenshot = QCheckBox("Debug screenshot")
        g.addWidget(self.headless,         row, 0, 1, 2)
        g.addWidget(self.no_http_check,    row, 2, 1, 2); row += 1
        g.addWidget(self.debug_screenshot, row, 0, 1, 2); row += 1

        self.setLayout(g)


# ── RUN tab ──────────────────────────────────────────────────────
class RunTab(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout()
        outer.setSpacing(10)

        # top area: params + niches side by side
        top = QHBoxLayout()
        top.setSpacing(12)

        # left: comune + common params
        left_box = QGroupBox("Single run  —  run.py")
        left_g = QVBoxLayout()

        row0 = QHBoxLayout()
        row0.addWidget(lbl("Comune / City"))
        self.comune = QLineEdit(); self.comune.setPlaceholderText("es. Bologna  /  Austin TX")
        row0.addWidget(self.comune)

        row1 = QHBoxLayout()
        row1.addWidget(lbl("Output CSV"))
        self.output = QLineEdit("output/debug_run.csv")
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse)
        row1.addWidget(self.output); row1.addWidget(btn_browse)

        self.common = CommonParams()

        left_g.addLayout(row0)
        left_g.addLayout(row1)
        left_g.addWidget(self.common)
        left_g.addStretch()
        left_box.setLayout(left_g)

        # right: niches
        self.niches = NicheSelector()

        top.addWidget(left_box, 3)
        top.addWidget(self.niches, 2)

        # buttons
        btn_row = QHBoxLayout()
        self.btn_run  = QPushButton("Run")
        self.btn_stop = QPushButton("Stop"); self.btn_stop.setObjectName("stop"); self.btn_stop.setEnabled(False)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_stop)

        # terminal
        term_lbl = section_label("Output")
        self.terminal = QTextEdit(); self.terminal.setReadOnly(True); self.terminal.setMinimumHeight(200)

        outer.addLayout(top)
        outer.addLayout(btn_row)
        outer.addWidget(term_lbl)
        outer.addWidget(self.terminal)
        self.setLayout(outer)

        self.btn_run.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self._runner = None

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Output CSV", "", "CSV (*.csv)")
        if path:
            self.output.setText(path)

    def _build_cmd(self):
        c = self.common
        sel = self.niches.selected()
        if not sel:
            return None, "Seleziona almeno una nicchia."
        comune = self.comune.text().strip()
        if not comune:
            return None, "Inserisci il comune / city."

        cmd = [sys.executable, "run.py",
               "--comune", comune,
               "--nicchie"] + sel + [
               "--min-reviews", str(c.min_reviews.value()),
               "--max-reviews", str(c.max_reviews.value()),
               "--scroll-times", str(c.scroll_times.value()),
               "--lang", c.lang.currentText(),
               "--log-level", c.log_level.currentText(),
               "--output", self.output.text().strip() or "output/debug_run.csv",
        ]
        if c.max_results.value() > 0:
            cmd += ["--max-results", str(c.max_results.value())]
        if c.headless.isChecked():        cmd.append("--headless")
        if c.no_http_check.isChecked():   cmd.append("--no-http-check")
        if c.debug_screenshot.isChecked():cmd.append("--debug-screenshot")
        return cmd, None

    def _start(self):
        cmd, err = self._build_cmd()
        if err:
            self.terminal.append(f"[error] {err}"); return
        self.terminal.clear()
        self.terminal.append("$ " + " ".join(shlex.quote(a) for a in cmd) + "\n")
        self._runner = Runner(cmd)
        self._runner.line_out.connect(self._append)
        self._runner.finished.connect(self._done)
        self._runner.start()
        self.btn_run.setEnabled(False); self.btn_stop.setEnabled(True)

    def _stop(self):
        if self._runner: self._runner.stop()

    def _append(self, line):
        self.terminal.append(line)
        self.terminal.moveCursor(QTextCursor.End)

    def _done(self, code):
        self.terminal.append(f"\n[process exited with code {code}]")
        self.btn_run.setEnabled(True); self.btn_stop.setEnabled(False)


# ── BATCH tab ────────────────────────────────────────────────────
class BatchTab(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout()
        outer.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)

        # left params
        left_box = QGroupBox("Batch run  —  run_batch.py")
        left_g = QVBoxLayout()

        # input CSV
        r0 = QHBoxLayout()
        r0.addWidget(lbl("Input CSV"))
        self.input_csv = QLineEdit(); self.input_csv.setPlaceholderText("path/to/cities.csv")
        btn_i = QPushButton("..."); btn_i.setFixedWidth(32); btn_i.clicked.connect(self._browse_in)
        r0.addWidget(self.input_csv); r0.addWidget(btn_i)

        # output CSV
        r1 = QHBoxLayout()
        r1.addWidget(lbl("Output CSV"))
        self.output = QLineEdit("output/batch_results.csv")
        btn_o = QPushButton("..."); btn_o.setFixedWidth(32); btn_o.clicked.connect(self._browse_out)
        r1.addWidget(self.output); r1.addWidget(btn_o)

        # state filter
        r2 = QHBoxLayout()
        r2.addWidget(lbl("State filter"))
        self.state = QLineEdit(); self.state.setPlaceholderText("TX  /  lascia vuoto = tutti")
        r2.addWidget(self.state)

        # pause
        pause_box = QGroupBox("Anti-ban pause (seconds)")
        pg = QHBoxLayout()
        pg.addWidget(lbl("Min"))
        self.pause_min = QDoubleSpinBox(); self.pause_min.setRange(0, 300); self.pause_min.setValue(5.0); self.pause_min.setSingleStep(0.5)
        pg.addWidget(self.pause_min)
        pg.addWidget(lbl("Max"))
        self.pause_max = QDoubleSpinBox(); self.pause_max.setRange(0, 300); self.pause_max.setValue(15.0); self.pause_max.setSingleStep(0.5)
        pg.addWidget(self.pause_max)
        pause_box.setLayout(pg)

        self.common = CommonParams()
        self.common.max_reviews.setValue(100)
        self.common.max_results.setSpecialValueText("auto")
        self.common.max_results.setValue(0)

        left_g.addLayout(r0)
        left_g.addLayout(r1)
        left_g.addLayout(r2)
        left_g.addWidget(pause_box)
        left_g.addWidget(self.common)
        left_g.addStretch()
        left_box.setLayout(left_g)

        self.niches = NicheSelector()

        top.addWidget(left_box, 3)
        top.addWidget(self.niches, 2)

        # buttons
        btn_row = QHBoxLayout()
        self.btn_run  = QPushButton("Run Batch")
        self.btn_stop = QPushButton("Stop"); self.btn_stop.setObjectName("stop"); self.btn_stop.setEnabled(False)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_stop)

        term_lbl = section_label("Output")
        self.terminal = QTextEdit(); self.terminal.setReadOnly(True); self.terminal.setMinimumHeight(200)

        outer.addLayout(top)
        outer.addLayout(btn_row)
        outer.addWidget(term_lbl)
        outer.addWidget(self.terminal)
        self.setLayout(outer)

        self.btn_run.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self._runner = None

    def _browse_in(self):
        path, _ = QFileDialog.getOpenFileName(self, "Input CSV", "", "CSV (*.csv)")
        if path: self.input_csv.setText(path)

    def _browse_out(self):
        path, _ = QFileDialog.getSaveFileName(self, "Output CSV", "", "CSV (*.csv)")
        if path: self.output.setText(path)

    def _build_cmd(self):
        c = self.common
        sel = self.niches.selected()
        if not sel:
            return None, "Seleziona almeno una nicchia."
        inp = self.input_csv.text().strip()
        if not inp:
            return None, "Specifica il CSV delle città."

        cmd = [sys.executable, "run_batch.py",
               "--input", inp,
               "--nicchie"] + sel + [
               "--min-reviews", str(c.min_reviews.value()),
               "--max-reviews", str(c.max_reviews.value()),
               "--scroll-times", str(c.scroll_times.value()),
               "--lang", c.lang.currentText(),
               "--log-level", c.log_level.currentText(),
               "--output", self.output.text().strip() or "output/batch_results.csv",
               "--pause-min", str(self.pause_min.value()),
               "--pause-max", str(self.pause_max.value()),
        ]
        if c.max_results.value() > 0:
            cmd += ["--max-results", str(c.max_results.value())]
        state = self.state.text().strip()
        if state: cmd += ["--state", state]
        if c.headless.isChecked():         cmd.append("--headless")
        if c.no_http_check.isChecked():    cmd.append("--no-http-check")
        if c.debug_screenshot.isChecked(): cmd.append("--debug-screenshot")
        return cmd, None

    def _start(self):
        cmd, err = self._build_cmd()
        if err:
            self.terminal.append(f"[error] {err}"); return
        self.terminal.clear()
        self.terminal.append("$ " + " ".join(shlex.quote(a) for a in cmd) + "\n")
        self._runner = Runner(cmd)
        self._runner.line_out.connect(self._append)
        self._runner.finished.connect(self._done)
        self._runner.start()
        self.btn_run.setEnabled(False); self.btn_stop.setEnabled(True)

    def _stop(self):
        if self._runner: self._runner.stop()

    def _append(self, line):
        self.terminal.append(line)
        self.terminal.moveCursor(QTextCursor.End)

    def _done(self, code):
        self.terminal.append(f"\n[process exited with code {code}]")
        self.btn_run.setEnabled(True); self.btn_stop.setEnabled(False)


# ── main window ──────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Local Contractors")
        self.resize(1020, 800)

        tabs = QTabWidget()
        tabs.addTab(RunTab(),   "Single Run")
        tabs.addTab(BatchTab(), "Batch Run")

        self.setCentralWidget(tabs)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(BASE_SS)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
