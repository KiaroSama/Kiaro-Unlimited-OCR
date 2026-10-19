"""Native local PDF/RTL OCR workspace with an isolated CUDA worker."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr import ROOT, configure_paths, start_log
from page_selection import parse_pages
from PySide6.QtCore import QProcess, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase, QImage, QPixmap, QTextOption
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QVBoxLayout, QWidget)

STYLE = """
QWidget { background:#111820; color:#e8edf5; font-family:'Segoe UI'; font-size:16px; }
QLineEdit,QComboBox,QSpinBox,QPlainTextEdit { background:#1b2633; border:1px solid #40536b;
 border-radius:6px; padding:7px; selection-background-color:#315c87; }
QPushButton { background:#26394d; border:1px solid #526b88; border-radius:6px; padding:9px 16px; }
QPushButton:hover { background:#344e68; }
QPushButton:focus,QLineEdit:focus,QComboBox:focus,QSpinBox:focus { border:2px solid #7db3ff; }
QPushButton:disabled { color:#9ca8b8; background:#1c2632; }
QPushButton#start { background:#245746; color:#c8ffd8; border-color:#6de4ad; }
QPushButton#cancel { color:#ffb1c4; border-color:#e17c9a; }
QLabel#title { font-size:25px; font-weight:600; color:#7db3ff; }
QLabel#hint { color:#a9bdd5; }
QProgressBar { border:1px solid #40536b; border-radius:5px; text-align:center; min-height:23px; }
QProgressBar::chunk { background:#277e75; }
QSplitter::handle { background:#40536b; width:4px; }
"""


class Workspace(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Unlimited-OCR | Local CUDA Workspace")
        self.resize(1320, 860)
        self.document = None
        self.source = None
        self.run_dir = None
        self.event_offset = 0
        self.event_buffer = ""
        self.closing = False
        self.log, _ = start_log()
        self.log.info("GUI startup")
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_diagnostics)
        self.process.finished.connect(self.worker_finished)
        self.process.errorOccurred.connect(self.worker_error)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.read_events)
        container = QWidget()
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(22, 18, 22, 18)
        title = QLabel("Unlimited-OCR  /  Document Workspace")
        title.setObjectName("title")
        layout.addWidget(title)
        hint = QLabel("Original BF16  •  NVIDIA CUDA  •  Local files only  •  Review OCR before use")
        hint.setObjectName("hint")
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("Choose an image or PDF — Persian paths supported")
        self.path.setAccessibleName("Source document path")
        self.open_button = QPushButton("Open document…")
        self.open_button.clicked.connect(self.choose_file)
        row.addWidget(self.path, 1)
        row.addWidget(self.open_button)
        layout.addLayout(row)
        settings = QHBoxLayout()
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText("All pages or 1,3,10-20 | Persian digits accepted")
        self.ranges.setAccessibleName("PDF page selection")
        settings.addWidget(QLabel("Pages"))
        settings.addWidget(self.ranges, 1)
        self.mode = QComboBox()
        self.mode.addItems(["base", "gundam"])
        self.mode.setAccessibleName("OCR mode")
        self.mode.setToolTip("Base: lower VRAM. Gundam: tiled small text, higher VRAM.")
        settings.addWidget(QLabel("Mode"))
        settings.addWidget(self.mode)
        self.start_button = QPushButton("Start OCR")
        self.start_button.setObjectName("start")
        self.start_button.clicked.connect(self.start_run)
        self.cancel_button = QPushButton("Cancel / keep results")
        self.cancel_button.setObjectName("cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_run)
        settings.addWidget(self.start_button)
        settings.addWidget(self.cancel_button)
        layout.addLayout(settings)
        nav = QHBoxLayout()
        self.page_number = QSpinBox()
        self.page_number.setRange(1, 1)
        self.page_number.setAccessibleName("Preview source page")
        self.page_number.valueChanged.connect(self.preview_page)
        self.page_label = QLabel("No document loaded")
        self.output_button = QPushButton("Open saved results")
        self.output_button.setEnabled(False)
        self.output_button.clicked.connect(self.open_output)
        nav.addWidget(QLabel("Preview page"))
        nav.addWidget(self.page_number)
        nav.addWidget(self.page_label, 1)
        nav.addWidget(self.output_button)
        layout.addLayout(nav)
        splitter = QSplitter(Qt.Horizontal)
        self.preview = QLabel("Open a document to preview its source pages")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumWidth(200)
        scroll = QScrollArea()
        scroll.setWidget(self.preview)
        scroll.setWidgetResizable(True)
        splitter.addWidget(scroll)
        panel = QWidget()
        text_layout = QVBoxLayout(panel)
        text_layout.setContentsMargins(6, 0, 0, 0)
        self.text_title = QLabel("Recognized text — live, not yet verified")
        text_layout.addWidget(self.text_title)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setAccessibleName("Recognized OCR text")
        option = self.text.document().defaultTextOption()
        option.setTextDirection(Qt.LayoutDirectionAuto)
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.text.document().setDefaultTextOption(option)
        self.text.setFont(QFont("Segoe UI", 13))
        text_layout.addWidget(self.text)
        splitter.addWidget(panel)
        splitter.setSizes([600, 660])
        layout.addWidget(splitter, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("0% — 0 pages completed")
        layout.addWidget(self.progress)
        self.status = QLabel("Ready. Select pages and a mode, then start.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumHeight(100)
        self.diagnostics.setMaximumBlockCount(200)
        self.diagnostics.setAccessibleName("Runtime diagnostics")
        layout.addWidget(self.diagnostics)

    def choose_file(self):
        name, _ = QFileDialog.getOpenFileName(self, "Open document", "", "Documents (*.pdf *.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp)")
        if name:
            self.load_source(Path(name))

    def load_source(self, path):
        try:
            import pymupdf
            if self.document:
                self.document.close()
                self.document = None
            path = path.expanduser().resolve()
            if not path.is_file():
                raise ValueError("Source file does not exist.")
            if path.suffix.lower() == ".pdf":
                self.document = pymupdf.open(path)
                if self.document.needs_pass or len(self.document) < 1:
                    raise ValueError("PDF must be unlocked and contain pages.")
            self.source = path
            self.path.setText(str(path))
            total = len(self.document) if self.document else 1
            self.page_number.setRange(1, total)
            self.page_number.setValue(1)
            self.page_label.setText(f"{total} source pages")
            self.preview_page(1)
            self.status.setText("Source loaded. Empty page selection means all pages.")
        except Exception as error:
            self.source = None
            self.status.setText(f"Cannot open document: {error}")

    def preview_page(self, number):
        if not self.source:
            return
        if self.document:
            pix = self.document[number - 1].get_pixmap(dpi=100, alpha=False)
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            picture = QPixmap.fromImage(image)
        else:
            picture = QPixmap(str(self.source))
        if picture.isNull():
            self.status.setText("Cannot render source preview.")
            return
        self.preview.setPixmap(picture.scaledToWidth(580, Qt.SmoothTransformation))

    def start_run(self):
        if self.process.state() != QProcess.NotRunning:
            return
        if not self.source or self.path.text() != str(self.source):
            self.load_source(Path(self.path.text().strip().strip('"')))
        if not self.source:
            return
        try:
            selected = parse_pages(self.ranges.text(), len(self.document) if self.document else 1)
        except ValueError as error:
            self.status.setText(f"Invalid pages: {error}")
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.run_dir = ROOT / "outputs" / f"ocr_{stamp}_{uuid4().hex[:8]}"
        self.event_offset, self.event_buffer = 0, ""
        self.text.clear()
        self.progress.setRange(0, 0)
        self.status.setText(f"Loading CUDA model — {len(selected)} selected pages. Percentage starts after page completion.")
        args = ["-I", "-X", "utf8", "-u", str(ROOT / "scripts" / "ocr.py"), str(self.source),
                "--page-selection", self.ranges.text(), "--mode", self.mode.currentText(),
                "--run-dir", str(self.run_dir)]
        self.process.setProgram(sys.executable)
        self.process.setArguments(args)
        self.process.setWorkingDirectory(str(ROOT))
        self.set_busy(True)
        self.process.start()
        self.timer.start()

    def set_busy(self, busy):
        for control in (self.open_button, self.path, self.ranges, self.mode, self.start_button):
            control.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def read_diagnostics(self):
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.diagnostics.appendPlainText(data.strip())

    def read_events(self):
        if not self.run_dir or not (self.run_dir / "events.jsonl").exists():
            return
        with (self.run_dir / "events.jsonl").open("r", encoding="utf-8") as handle:
            handle.seek(self.event_offset)
            self.event_buffer += handle.read()
            self.event_offset = handle.tell()
        while "\n" in self.event_buffer:
            line, self.event_buffer = self.event_buffer.split("\n", 1)
            self.apply_event(json.loads(line))

    def apply_event(self, event):
        kind = event["kind"]
        if kind == "page_start":
            self.page_number.setValue(event["page"])
            self.text_title.setText(f"Source page {event['page']} — live OCR")
            self.text.clear()
            self.progress.setRange(0, 100)
            self.status.setText(f"Processing page {event['page']} | {event['completed']}/{event['total']} saved")
        elif kind == "text":
            self.text.setPlainText(event["text"])
            self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
        elif kind in ("page_done", "finished"):
            self.progress.setRange(0, 100)
            self.progress.setValue(int(event["percent"]))
            self.progress.setFormat(f"{event['percent']}% — {event['completed']}/{event['total']} pages saved")
            self.output_button.setEnabled(True)
            self.status.setText(f"{event['completed']}/{event['total']} pages saved — {event['percent']}%")
            if kind == "finished":
                self.status.setText(f"{event['status'].capitalize()} — saved results: {self.run_dir}")

    def cancel_run(self):
        if self.run_dir:
            self.request_cancel()
            self.status.setText("Cancelling at next generation boundary. Completed/partial text stays saved.")
            self.cancel_button.setEnabled(False)

    def request_cancel(self):
        if self.run_dir and self.run_dir.exists():
            (self.run_dir / "cancel.request").touch()
        elif self.process.state() != QProcess.NotRunning:
            QTimer.singleShot(200, self.request_cancel)

    def worker_error(self, error):
        self.status.setText(f"Worker process error: {self.process.errorString()}")
        self.set_busy(False)

    def worker_finished(self, code, status):
        self.read_diagnostics()
        self.read_events()
        self.timer.stop()
        self.set_busy(False)
        if code not in (0, 130):
            self.status.setText(f"Worker exited {code}; checkpoints remain in {self.run_dir}. See diagnostics.")
        if self.closing:
            self.close()

    def open_output(self):
        if self.run_dir and self.run_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.run_dir)))

    def closeEvent(self, event):
        if self.process.state() != QProcess.NotRunning:
            self.closing = True
            self.cancel_run()
            event.ignore()
            return
        if self.document:
            self.document.close()
        self.log.info("GUI shutdown")
        for handler in list(self.log.handlers):
            handler.close()
            self.log.removeHandler(handler)
        event.accept()


def load_system_fonts(app):
    # Qt offscreen (and some sandboxed hosts) enumerates zero Windows fonts.
    # Load installed files locally; do not download or redistribute font bytes.
    import os
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    if not QFontDatabase.families():
        for name in ("segoeui.ttf", "segoeuib.ttf", "tahoma.ttf", "tahomabd.ttf"):
            path = fonts / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Segoe UI", 12))


def main():
    configure_paths()
    app = QApplication(sys.argv)
    load_system_fonts(app)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Workspace()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
