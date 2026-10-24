"""
iMessage Export GUI
A simple Windows front end for backing up an iPhone and exporting its messages.

https://github.com/Kungpow1989/imessage-export-gui

The message export itself is done by imessage-exporter by Christopher Sardegna
(ReagentX): https://github.com/ReagentX/imessage-exporter
iPhone backups are made with pymobiledevice3 by doronz88 and contributors:
https://github.com/doronz88/pymobiledevice3

This program is free software under the GNU General Public License v3.0.

Step 1 backs up a connected iPhone with pymobiledevice3 (same kind of backup
the Apple Devices app or iTunes makes). Steps 2 to 4 pick a backup and export
its messages with ReagentX's imessage-exporter.

Running from source (setup.bat installs all of these; the release .exe
already includes everything except the Apple Devices app):
    pip install PySide6 pymobiledevice3
    Apple Devices app (or iTunes), for the iPhone USB driver
    imessage-exporter.exe on PATH, in %USERPROFILE%\\.cargo\\bin,
    next to this script, or picked with the Browse button.
"""

import datetime
import importlib.util
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QDate, QProcess, QProcessEnvironment, QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "iMessage Export"
APP_VERSION = "1.0.0"
FROZEN = getattr(sys, "frozen", False)
PMD3_FLAG = "--pymobiledevice3"
# What to tell people when a piece is missing, depending on how they run the app
REINSTALL_HINT = (
    "Download the latest release again from github.com/Kungpow1989/imessage-export-gui"
    if FROZEN
    else "Run setup.bat again"
)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PROGRESS_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)%\|")

FORMATS = [
    ("HTML (best for reading and printing)", "html"),
    ("Plain text", "txt"),
]

COPY_METHODS = [
    ("Don't copy attachments", "disabled"),
    ("Copy attachments as they are", "clone"),
    ("Copy and convert photos to JPEG", "basic"),
    ("Copy and convert photos, audio and video", "full"),
]


# ---------- Helpers ----------


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def icon_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", app_dir()))
    return base / "assets" / "icon.ico"


def python_exe() -> str:
    """The console python.exe, even when this app was started with pythonw.exe."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def pymobiledevice3_command() -> list[str] | None:
    if FROZEN:
        # The .exe bundles pymobiledevice3 and runs it when started with PMD3_FLAG
        return [sys.executable, PMD3_FLAG]
    if importlib.util.find_spec("pymobiledevice3"):
        return [python_exe(), "-m", "pymobiledevice3"]
    found = shutil.which("pymobiledevice3")
    return [found] if found else None


def find_exporter() -> str:
    # The copy shipped next to the app comes first, so a release always uses its bundled version
    bundled = app_dir() / "imessage-exporter.exe"
    if bundled.exists():
        return str(bundled)
    found = shutil.which("imessage-exporter")
    if found:
        return found
    cargo = Path.home() / ".cargo" / "bin" / "imessage-exporter.exe"
    return str(cargo) if cargo.exists() else ""


def backup_roots() -> list[Path]:
    """Places iTunes and the Apple Devices app keep iPhone backups on Windows."""
    roots = []
    appdata = os.environ.get("APPDATA")
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    candidates = [
        Path(appdata) / "Apple Computer" / "MobileSync" / "Backup" if appdata else None,
        Path(profile) / "Apple" / "MobileSync" / "Backup",
        Path(profile) / "Apple Computer" / "MobileSync" / "Backup",
    ]
    for c in candidates:
        if c and c.is_dir() and c not in roots:
            roots.append(c)
    return roots


def default_backup_root() -> str:
    roots = backup_roots()
    if roots:
        return str(roots[0])
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    return str(Path(profile) / "Apple" / "MobileSync" / "Backup")


def read_backup(folder: Path) -> dict | None:
    """Pull device name, date and encryption state from a backup folder."""
    if not (folder / "Manifest.plist").exists():
        return None
    info = {}
    try:
        with open(folder / "Info.plist", "rb") as f:
            info = plistlib.load(f)
    except Exception:
        pass
    encrypted = False
    try:
        with open(folder / "Manifest.plist", "rb") as f:
            encrypted = bool(plistlib.load(f).get("IsEncrypted", False))
    except Exception:
        pass
    date = info.get("Last Backup Date")
    if not isinstance(date, datetime.datetime):
        date = datetime.datetime.fromtimestamp(folder.stat().st_mtime)
    return {
        "path": str(folder),
        "name": info.get("Device Name") or info.get("Display Name") or folder.name,
        "ios": info.get("Product Version", ""),
        "date": date,
        "encrypted": encrypted,
    }


def find_backups(extra_root: str = "") -> list[dict]:
    roots = backup_roots()
    if extra_root and Path(extra_root).is_dir() and Path(extra_root) not in roots:
        roots.append(Path(extra_root))
    backups = []
    for root in roots:
        try:
            children = list(root.iterdir())
        except Exception:
            continue
        for child in children:
            if child.is_dir():
                b = read_backup(child)
                if b:
                    backups.append(b)
    backups.sort(key=lambda b: b["date"], reverse=True)
    return backups


def safe_name(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", text).strip(" .") or "iPhone"


def free_space_text(path: str) -> str:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        free = shutil.disk_usage(p).free
        return f"{free / 1024**3:.1f} GB free"
    except Exception:
        return ""


def child_env(extra: dict | None = None) -> QProcessEnvironment:
    env = QProcessEnvironment.systemEnvironment()
    env.insert("NO_COLOR", "1")
    env.insert("PYTHONIOENCODING", "utf-8")
    env.insert("PYTHONUTF8", "1")
    for k, v in (extra or {}).items():
        env.insert(k, v)
    return env


# ---------- Main window ----------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(840, 980)
        self.settings = QSettings("imessage-export-gui", "iMessageExportGUI")
        self.process: QProcess | None = None
        self.dev_process: QProcess | None = None
        self.backups: list[dict] = []
        self.last_export_dir = ""
        self.mode = ""
        self.out_buffer = ""
        self.pending_udid = ""

        central = QWidget()
        layout = QVBoxLayout(central)

        layout.addWidget(self._build_device_group())
        layout.addWidget(self._build_backup_group())
        layout.addWidget(self._build_options_group())
        layout.addWidget(self._build_output_group())
        layout.addWidget(self._build_tool_group())

        # Command preview
        self.preview = QLineEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Consolas", 9))
        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("Command:"))
        preview_row.addWidget(self.preview)
        layout.addLayout(preview_row)

        # Buttons
        buttons = QHBoxLayout()
        self.run_btn = QPushButton("Export messages")
        self.run_btn.setMinimumHeight(36)
        self.run_btn.setStyleSheet("font-weight: bold;")
        self.diag_btn = QPushButton("Run diagnostics")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.open_btn = QPushButton("Open export folder")
        self.open_btn.setEnabled(False)
        for b in (self.run_btn, self.diag_btn, self.cancel_btn, self.open_btn):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setMaximumHeight(14)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setMinimumHeight(140)
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.log, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(central)
        self.setCentralWidget(scroll)

        self.status = QLabel("Ready")
        self.statusBar().addWidget(self.status)

        self.run_btn.clicked.connect(self.start_export)
        self.diag_btn.clicked.connect(self.start_diagnostics)
        self.cancel_btn.clicked.connect(self.cancel)
        self.open_btn.clicked.connect(self.open_export_folder)

        self._load_settings()
        self.refresh_backups()
        self.check_exporter()
        self.update_preview()
        self.find_devices()

    # ---------- UI builders ----------

    def _build_device_group(self) -> QGroupBox:
        box = QGroupBox("1. Back up the iPhone (skip this if you already have a recent backup)")
        form = QFormLayout(box)

        row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.find_btn = QPushButton("Find iPhone")
        row.addWidget(self.device_combo, 1)
        row.addWidget(self.find_btn)
        form.addRow("iPhone:", row)

        root_row = QHBoxLayout()
        self.backup_root_edit = QLineEdit()
        root_browse = QPushButton("Browse...")
        self.root_space = QLabel()
        root_row.addWidget(self.backup_root_edit, 1)
        root_row.addWidget(self.root_space)
        root_row.addWidget(root_browse)
        form.addRow("Save backups in:", root_row)

        go_row = QHBoxLayout()
        self.full_backup = QCheckBox("Full backup (slower, starts fresh instead of updating the last one)")
        self.backup_btn = QPushButton("Back up now")
        self.backup_btn.setMinimumHeight(32)
        self.backup_btn.setStyleSheet("font-weight: bold;")
        go_row.addWidget(self.full_backup)
        go_row.addStretch()
        go_row.addWidget(self.backup_btn)
        form.addRow("", go_row)

        self.device_hint = QLabel(
            "Plug the iPhone in with a cable and unlock it. Tap Trust if it asks, "
            "and enter your passcode on the phone when the backup starts."
        )
        self.device_hint.setWordWrap(True)
        self.device_hint.setStyleSheet("color: palette(mid);")
        form.addRow("", self.device_hint)

        self.find_btn.clicked.connect(self.find_devices)
        self.backup_btn.clicked.connect(self.start_backup)
        root_browse.clicked.connect(self.browse_backup_root)
        self.backup_root_edit.textChanged.connect(
            lambda t: self.root_space.setText(free_space_text(t) if t else "")
        )
        self.device_combo.currentIndexChanged.connect(self._update_backup_button)
        return box

    def _build_backup_group(self) -> QGroupBox:
        box = QGroupBox("2. Pick a backup")
        form = QFormLayout(box)

        row = QHBoxLayout()
        self.backup_combo = QComboBox()
        self.backup_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        refresh = QPushButton("Refresh")
        browse = QPushButton("Browse...")
        row.addWidget(self.backup_combo, 1)
        row.addWidget(refresh)
        row.addWidget(browse)
        form.addRow("Backup:", row)

        self.backup_info = QLabel()
        self.backup_info.setWordWrap(True)
        self.backup_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("", self.backup_info)

        pw_row = QHBoxLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Backup password (only needed for encrypted backups)")
        self.show_pw = QCheckBox("Show")
        pw_row.addWidget(self.password, 1)
        pw_row.addWidget(self.show_pw)
        form.addRow("Password:", pw_row)

        refresh.clicked.connect(self.refresh_backups)
        browse.clicked.connect(self.browse_backup)
        self.backup_combo.currentIndexChanged.connect(self.backup_changed)
        self.show_pw.toggled.connect(
            lambda on: self.password.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        )
        self.password.textChanged.connect(self.update_preview)
        return box

    def _build_options_group(self) -> QGroupBox:
        box = QGroupBox("3. What to export")
        form = QFormLayout(box)

        self.format_combo = QComboBox()
        for label, value in FORMATS:
            self.format_combo.addItem(label, value)
        form.addRow("Format:", self.format_combo)

        self.copy_combo = QComboBox()
        for label, value in COPY_METHODS:
            self.copy_combo.addItem(label, value)
        form.addRow("Attachments:", self.copy_combo)

        date_row = QHBoxLayout()
        self.use_dates = QCheckBox("Only messages from")
        self.start_date = QDateEdit(QDate.currentDate().addYears(-1))
        self.end_date = QDateEdit(QDate.currentDate())
        for d in (self.start_date, self.end_date):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")
            d.setEnabled(False)
        date_row.addWidget(self.use_dates)
        date_row.addWidget(self.start_date)
        date_row.addWidget(QLabel("to"))
        date_row.addWidget(self.end_date)
        date_row.addWidget(QLabel("(inclusive)"))
        date_row.addStretch()
        form.addRow("Dates:", date_row)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Blank for everyone. e.g. 5035551234, Alex, someone@icloud.com")
        self.filter_edit.setToolTip(
            "Names, numbers or emails, separated by commas.\n"
            "Every conversation with a match is exported, including group chats."
        )
        form.addRow("Only these people:", self.filter_edit)

        name_row = QHBoxLayout()
        self.my_name = QLineEdit()
        self.my_name.setPlaceholderText('Shown instead of "Me"')
        self.caller_id = QCheckBox("Use my phone number instead")
        name_row.addWidget(self.my_name, 1)
        name_row.addWidget(self.caller_id)
        form.addRow("My name:", name_row)

        self.no_lazy = QCheckBox("Load all images up front (better for printing to PDF, slower to open)")
        form.addRow("", self.no_lazy)

        self.use_dates.toggled.connect(self.start_date.setEnabled)
        self.use_dates.toggled.connect(self.end_date.setEnabled)
        self.caller_id.toggled.connect(lambda on: self.my_name.setEnabled(not on))
        self.format_combo.currentIndexChanged.connect(self._format_changed)
        for w in (self.format_combo, self.copy_combo):
            w.currentIndexChanged.connect(self.update_preview)
        for w in (self.use_dates, self.caller_id, self.no_lazy):
            w.toggled.connect(self.update_preview)
        for w in (self.start_date, self.end_date):
            w.dateChanged.connect(self.update_preview)
        for w in (self.filter_edit, self.my_name):
            w.textChanged.connect(self.update_preview)
        return box

    def _build_output_group(self) -> QGroupBox:
        box = QGroupBox("4. Save export to")
        form = QFormLayout(box)

        row = QHBoxLayout()
        self.out_edit = QLineEdit()
        browse = QPushButton("Browse...")
        row.addWidget(self.out_edit, 1)
        row.addWidget(browse)
        form.addRow("Folder:", row)

        self.subfolder = QCheckBox("Put each export in its own dated subfolder")
        self.subfolder.setChecked(True)
        self.open_when_done = QCheckBox("Open the folder when finished")
        self.open_when_done.setChecked(True)
        self.space_label = QLabel()
        opts = QHBoxLayout()
        opts.addWidget(self.subfolder)
        opts.addWidget(self.open_when_done)
        opts.addStretch()
        opts.addWidget(self.space_label)
        form.addRow("", opts)

        browse.clicked.connect(self.browse_output)
        self.out_edit.textChanged.connect(self._output_changed)
        self.subfolder.toggled.connect(self.update_preview)
        return box

    def _build_tool_group(self) -> QGroupBox:
        box = QGroupBox("imessage-exporter")
        form = QFormLayout(box)
        row = QHBoxLayout()
        self.exe_edit = QLineEdit()
        browse = QPushButton("Browse...")
        row.addWidget(self.exe_edit, 1)
        row.addWidget(browse)
        form.addRow("Program:", row)
        self.exe_status = QLabel()
        form.addRow("", self.exe_status)
        self.ignore_disk = QCheckBox("Skip the free disk space check")
        form.addRow("", self.ignore_disk)

        browse.clicked.connect(self.browse_exe)
        self.exe_edit.editingFinished.connect(self.check_exporter)
        self.exe_edit.textChanged.connect(self.update_preview)
        self.ignore_disk.toggled.connect(self.update_preview)
        return box

    # ---------- Settings ----------

    def _load_settings(self):
        s = self.settings
        default_out = str(Path.home() / "Documents" / "iMessage Exports")
        self.out_edit.setText(s.value("output", default_out))
        self.backup_root_edit.setText(s.value("backup_root", "") or default_backup_root())
        saved_exe = s.value("exe", "")
        if not saved_exe or not Path(saved_exe).exists():
            saved_exe = find_exporter()
        self.exe_edit.setText(saved_exe)
        self.format_combo.setCurrentIndex(int(s.value("format", 0)))
        self.copy_combo.setCurrentIndex(int(s.value("copy", 2)))
        self.my_name.setText(s.value("my_name", ""))
        self.caller_id.setChecked(s.value("caller_id", "false") == "true")
        self.subfolder.setChecked(s.value("subfolder", "true") == "true")
        self.open_when_done.setChecked(s.value("open_when_done", "true") == "true")
        self.no_lazy.setChecked(s.value("no_lazy", "false") == "true")
        self._format_changed()

    def _save_settings(self):
        s = self.settings
        s.setValue("output", self.out_edit.text())
        s.setValue("backup_root", self.backup_root_edit.text())
        s.setValue("exe", self.exe_edit.text())
        s.setValue("format", self.format_combo.currentIndex())
        s.setValue("copy", self.copy_combo.currentIndex())
        s.setValue("my_name", self.my_name.text())
        s.setValue("caller_id", "true" if self.caller_id.isChecked() else "false")
        s.setValue("subfolder", "true" if self.subfolder.isChecked() else "false")
        s.setValue("open_when_done", "true" if self.open_when_done.isChecked() else "false")
        s.setValue("no_lazy", "true" if self.no_lazy.isChecked() else "false")
        s.setValue("last_backup", self.current_backup_path())

    def closeEvent(self, event):
        if self.process and self.process.state() != QProcess.NotRunning:
            what = "A backup" if self.mode == "backup" else "An export"
            answer = QMessageBox.question(self, APP_NAME, f"{what} is still running. Stop it and quit?")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.process.kill()
            self.process.waitForFinished(3000)
        if self.dev_process and self.dev_process.state() != QProcess.NotRunning:
            self.dev_process.kill()
            self.dev_process.waitForFinished(2000)
        self._save_settings()
        event.accept()

    # ---------- Step 1: finding and backing up the iPhone ----------

    def find_devices(self):
        cmd = pymobiledevice3_command()
        self.device_combo.clear()
        if not cmd:
            self.device_combo.addItem("Backup tool not installed", "")
            self.device_hint.setText(
                "<span style='color:#b00020'>The backup tool (pymobiledevice3) is missing. "
                f"{REINSTALL_HINT}.</span>"
            )
            self._update_backup_button()
            return
        if self.dev_process and self.dev_process.state() != QProcess.NotRunning:
            return
        self.device_combo.addItem("Looking for iPhones...", "")
        self.find_btn.setEnabled(False)
        self._update_backup_button()

        proc = QProcess(self)
        proc.setProcessEnvironment(child_env())
        proc.finished.connect(lambda code, _status: self.devices_found(proc, code))
        proc.errorOccurred.connect(
            lambda err: self.devices_found(proc, -1) if err == QProcess.FailedToStart else None
        )
        self.dev_process = proc
        proc.start(cmd[0], cmd[1:] + ["usbmux", "list"])

    def devices_found(self, proc: QProcess, code: int):
        out = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        err = ANSI_RE.sub("", bytes(proc.readAllStandardError()).decode("utf-8", errors="replace"))
        data = []
        try:
            data = json.loads(out[out.index("[") : out.rindex("]") + 1])
        except Exception:
            pass

        self.device_combo.clear()
        for d in data if isinstance(data, list) else []:
            if d.get("ConnectionType", "USB") != "USB":
                continue
            udid = d.get("UniqueDeviceID") or d.get("Identifier") or d.get("SerialNumber")
            if not udid:
                continue
            name = d.get("DeviceName") or d.get("DeviceClass") or "iPhone"
            ios = f"  |  iOS {d['ProductVersion']}" if d.get("ProductVersion") else ""
            self.device_combo.addItem(f"{name}{ios}", udid)

        if self.device_combo.count():
            self.device_hint.setText(
                "Keep the iPhone unlocked. Tap Trust if it asks, and enter your passcode "
                "on the phone when the backup starts."
            )
        else:
            self.device_combo.addItem("No iPhone found", "")
            tip = (
                "No iPhone found. Plug it in with a cable, unlock it, tap Trust, then click Find iPhone."
            )
            low = err.lower()
            if "usbmux" in low or "connection refused" in low or "10061" in low:
                tip = (
                    "Can't talk to the iPhone driver. Install the Apple Devices app from the "
                    "Microsoft Store (or iTunes), then click Find iPhone."
                )
            elif code not in (0, -1) and err.strip():
                tip += f"\nDetails: {err.strip().splitlines()[-1][:200]}"
            elif code == -1:
                tip = f"Couldn't start the backup tool. {REINSTALL_HINT}."
            self.device_hint.setText(tip)
        self.find_btn.setEnabled(not self.is_busy())
        self._update_backup_button()

    def _update_backup_button(self, *_):
        has_device = bool(self.device_combo.currentData())
        self.backup_btn.setEnabled(has_device and not self.is_busy())

    def browse_backup_root(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Save iPhone backups in", self.backup_root_edit.text() or str(Path.home())
        )
        if folder:
            self.backup_root_edit.setText(str(Path(folder)))
            self.refresh_backups()

    def start_backup(self):
        udid = self.device_combo.currentData()
        cmd = pymobiledevice3_command()
        if not udid or not cmd:
            QMessageBox.warning(self, APP_NAME, "Plug in the iPhone and click Find iPhone first.")
            return
        root = self.backup_root_edit.text().strip()
        if not root:
            QMessageBox.warning(self, APP_NAME, "Pick a folder to save the backup in.")
            return
        root = str(Path(root))
        self.backup_root_edit.setText(root)
        try:
            Path(root).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't create the backup folder:\n{e}")
            return

        self._save_settings()
        self.pending_udid = udid
        args = cmd[1:] + ["backup2", "backup", root]
        if self.full_backup.isChecked():
            args.append("--full")
        shown = f'pymobiledevice3 backup2 backup "{root}"' + (" --full" if self.full_backup.isChecked() else "")
        self.start_process(cmd[0], args, "backup", shown, {"PYMOBILEDEVICE3_UDID": udid})
        self.append_log(
            "Unlock your iPhone. If it asks, tap Trust and enter your passcode to allow the backup.\n"
            "The first backup can take a while. Later ones only copy what changed.\n\n"
        )

    def select_backup_for(self, udid: str, root: str):
        self.refresh_backups()
        for candidate in (Path(root) / udid, Path(root) / udid.replace("-", "")):
            idx = self.backup_combo.findData(str(candidate))
            if idx >= 0:
                self.backup_combo.setCurrentIndex(idx)
                return True
        return False

    # ---------- Step 2: picking a backup ----------

    def refresh_backups(self):
        current = self.current_backup_path() or self.settings.value("last_backup", "")
        self.backups = find_backups(self.backup_root_edit.text().strip())
        self.backup_combo.blockSignals(True)
        self.backup_combo.clear()
        for b in list(self.backups):
            self._add_backup_item(b)
        if not self.backups:
            self.backup_combo.addItem("No backups yet. Use step 1 to make one.", "")
        self.backup_combo.blockSignals(False)
        if current:
            idx = self.backup_combo.findData(current)
            if idx < 0 and Path(current).is_dir():
                b = read_backup(Path(current))
                if b:
                    if not self.backups:
                        self.backup_combo.clear()
                    self._add_backup_item(b)
                    idx = self.backup_combo.count() - 1
            if idx >= 0:
                self.backup_combo.setCurrentIndex(idx)
        self.backup_changed()

    def _add_backup_item(self, b: dict):
        if not any(x["path"] == b["path"] for x in self.backups):
            self.backups.append(b)
        lock = " (encrypted)" if b["encrypted"] else ""
        label = f"{b['name']}  |  {b['date']:%d %b %Y %H:%M}{lock}"
        self.backup_combo.addItem(label, b["path"])

    def current_backup(self) -> dict | None:
        path = self.backup_combo.currentData()
        return next((b for b in self.backups if b["path"] == path), None)

    def current_backup_path(self) -> str:
        return self.backup_combo.currentData() or ""

    def backup_changed(self, *_):
        b = self.current_backup()
        if not b:
            looked = [str(r) for r in backup_roots()]
            if self.backup_root_edit.text() and self.backup_root_edit.text() not in looked:
                looked.append(self.backup_root_edit.text())
            self.backup_info.setText("Looked in: " + (", ".join(looked) or "no backup folders exist yet"))
            self.password.setEnabled(False)
        else:
            ios = f"iOS {b['ios']}  |  " if b["ios"] else ""
            enc = "Encrypted, password required" if b["encrypted"] else "Not encrypted"
            self.backup_info.setText(f"{ios}{enc}\n{b['path']}")
            self.password.setEnabled(b["encrypted"])
            if not b["encrypted"]:
                self.password.clear()
        self.update_preview()

    def browse_backup(self):
        roots = backup_roots()
        start = str(roots[0]) if roots else self.backup_root_edit.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Pick the iPhone backup folder", start)
        if not folder:
            return
        b = read_backup(Path(folder))
        if not b:
            QMessageBox.warning(
                self,
                APP_NAME,
                "That folder doesn't look like an iPhone backup.\n\n"
                "Pick the folder that contains Manifest.plist (usually a long string of letters and numbers).",
            )
            return
        idx = self.backup_combo.findData(b["path"])
        if idx < 0:
            if not self.current_backup_path():
                self.backup_combo.clear()
            self._add_backup_item(b)
            idx = self.backup_combo.count() - 1
        self.backup_combo.setCurrentIndex(idx)

    # ---------- Other UI handlers ----------

    def _format_changed(self, *_):
        self.no_lazy.setEnabled(self.format_combo.currentData() == "html")
        self.update_preview()

    def _output_changed(self, *_):
        self.space_label.setText(free_space_text(self.out_edit.text()) if self.out_edit.text() else "")
        self.update_preview()

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Save exports to", self.out_edit.text() or str(Path.home()))
        if folder:
            self.out_edit.setText(str(Path(folder)))

    def browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Find imessage-exporter.exe", str(Path.home()), "Programs (*.exe);;All files (*)"
        )
        if path:
            self.exe_edit.setText(str(Path(path)))
            self.check_exporter()

    def check_exporter(self):
        exe = self.exe_edit.text().strip()
        if not exe or not Path(exe).exists():
            self.exe_status.setText(
                f"<span style='color:#b00020'>Not found. {REINSTALL_HINT}, "
                "or pick imessage-exporter.exe with Browse.</span>"
            )
            return False
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            out = subprocess.run([exe, "-V"], capture_output=True, text=True, timeout=10, creationflags=flags)
            version = (out.stdout or out.stderr).strip()
            self.exe_status.setText(f"<span style='color:#1b7f3b'>Found: {version}</span>")
            return True
        except Exception as e:
            self.exe_status.setText(f"<span style='color:#b00020'>Couldn't run it: {e}</span>")
            return False

    # ---------- Steps 3 and 4: building the export command ----------

    def export_dir(self) -> str:
        base = self.out_edit.text().strip()
        if not self.subfolder.isChecked():
            return base
        b = self.current_backup()
        device = safe_name(b["name"]) if b else "iPhone"
        return str(Path(base) / f"{device} {datetime.datetime.now():%Y-%m-%d %H%M}")

    def build_args(self, diagnostics=False, out_dir=None) -> list[str]:
        args = ["-p", self.current_backup_path(), "-a", "iOS"]
        b = self.current_backup()
        if b and b["encrypted"] and self.password.text():
            args += ["-x", self.password.text()]
        if diagnostics:
            return ["-d"] + args

        args += ["-f", self.format_combo.currentData()]
        args += ["-c", self.copy_combo.currentData()]
        args += ["-o", out_dir or self.export_dir()]
        if self.use_dates.isChecked():
            args += ["-s", self.start_date.date().toString("yyyy-MM-dd")]
            # imessage-exporter's end date is exclusive, so add a day to make the picker inclusive
            args += ["-e", self.end_date.date().addDays(1).toString("yyyy-MM-dd")]
        people = ",".join(p.strip() for p in self.filter_edit.text().split(",") if p.strip())
        if people:
            args += ["-t", people]
        if self.caller_id.isChecked():
            args.append("-i")
        elif self.my_name.text().strip():
            args += ["-m", self.my_name.text().strip()]
        if self.no_lazy.isChecked() and self.format_combo.currentData() == "html":
            args.append("-l")
        if self.ignore_disk.isChecked():
            args.append("-b")
        return args

    def shown_command(self, args: list[str]) -> str:
        shown = []
        hide_next = False
        for a in args:
            if hide_next:
                shown.append("********")
                hide_next = False
                continue
            if a == "-x":
                hide_next = True
            shown.append(f'"{a}"' if " " in a or not a else a)
        exe = Path(self.exe_edit.text()).name or "imessage-exporter"
        return f"{exe} " + " ".join(shown)

    def update_preview(self, *_):
        if not hasattr(self, "preview"):
            return
        self.preview.setText(self.shown_command(self.build_args()))

    # ---------- Running ----------

    def validate(self, diagnostics=False) -> bool:
        if not self.check_exporter():
            QMessageBox.warning(self, APP_NAME, "Can't find imessage-exporter.exe. Set it in the bottom section.")
            return False
        b = self.current_backup()
        if not b:
            QMessageBox.warning(self, APP_NAME, "Pick a backup in step 2 first, or make one in step 1.")
            return False
        if b["encrypted"] and not self.password.text():
            QMessageBox.warning(
                self,
                APP_NAME,
                "This backup is encrypted. Enter the backup password you set in Apple Devices or iTunes.",
            )
            self.password.setFocus()
            return False
        if diagnostics:
            return True
        if not self.out_edit.text().strip():
            QMessageBox.warning(self, APP_NAME, "Pick a folder to save the export to.")
            return False
        if self.use_dates.isChecked() and self.start_date.date() > self.end_date.date():
            QMessageBox.warning(self, APP_NAME, "The start date is after the end date.")
            return False

        method = self.copy_combo.currentData()
        missing = []
        if method in ("basic", "full") and not shutil.which("magick"):
            missing.append("ImageMagick (for converting HEIC photos)")
        if method == "full" and not shutil.which("ffmpeg"):
            missing.append("ffmpeg (for converting audio and video)")
        if missing:
            answer = QMessageBox.question(
                self,
                APP_NAME,
                "These aren't installed, so some attachments may stay in their original format:\n\n- "
                + "\n- ".join(missing)
                + (
                    "\n\nYou can install them with:\nwinget install ImageMagick.ImageMagick Gyan.FFmpeg"
                    if FROZEN
                    else "\n\nRun setup.bat again to install them."
                )
                + "\n\nContinue anyway?",
            )
            if answer != QMessageBox.Yes:
                return False
        return True

    def start_export(self):
        if not self.validate():
            return
        out_dir = self.export_dir()
        try:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't create the export folder:\n{e}")
            return
        self.last_export_dir = out_dir
        self._save_settings()
        args = self.build_args(out_dir=out_dir)
        self.start_process(self.exe_edit.text().strip(), args, "export", self.shown_command(args))

    def start_diagnostics(self):
        if not self.validate(diagnostics=True):
            return
        args = self.build_args(diagnostics=True)
        self.start_process(self.exe_edit.text().strip(), args, "diagnostics", self.shown_command(args))

    def start_process(self, program: str, args: list[str], mode: str, shown: str, extra_env=None):
        self.mode = mode
        self.out_buffer = ""
        self.log.clear()
        self.append_log(f"> {shown}\n")

        self.process = QProcess(self)
        self.process.setProcessEnvironment(child_env(extra_env))
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.set_running(True)
        self.process.start(program, args)

        self.status.setText(
            {"export": "Exporting...", "backup": "Backing up iPhone...", "diagnostics": "Running diagnostics..."}[mode]
        )

    def is_busy(self) -> bool:
        return bool(self.process and self.process.state() != QProcess.NotRunning)

    def set_running(self, running: bool):
        for b in (self.run_btn, self.diag_btn, self.find_btn):
            b.setEnabled(not running)
        self.backup_btn.setEnabled(not running and bool(self.device_combo.currentData()))
        self.cancel_btn.setEnabled(running)
        if running:
            self.open_btn.setEnabled(False)
            if self.mode == "backup":
                self.progress.setRange(0, 100)
                self.progress.setValue(0)
                self.progress.setTextVisible(True)
            else:
                self.progress.setRange(0, 0)
                self.progress.setTextVisible(False)
        else:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.progress.setTextVisible(False)

    def read_output(self):
        raw = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.out_buffer += ANSI_RE.sub("", raw)
        *lines, self.out_buffer = self.out_buffer.split("\n")
        shown = []
        for line in lines:
            # Progress bars redraw with \r; keep only the latest state of each line
            seg = line.rstrip("\r").split("\r")[-1]
            if self.handle_progress(seg):
                continue
            shown.append(seg)
        self.handle_progress(self.out_buffer.split("\r")[-1])
        if shown:
            self.append_log("\n".join(shown) + "\n")

    def handle_progress(self, seg: str) -> bool:
        """For backups, turn tqdm progress lines into the progress bar instead of log spam."""
        if self.mode != "backup":
            return False
        m = PROGRESS_RE.search(seg)
        if not m:
            return False
        self.progress.setValue(min(100, int(float(m.group(1)))))
        return True

    def append_log(self, text: str):
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.append_log(f"\nCouldn't start the program. {REINSTALL_HINT}.\n")
            self.set_running(False)
            self._update_backup_button()
            self.status.setText("Failed to start")

    def finished(self, code: int, status):
        tail = self.out_buffer.split("\r")[-1].strip()
        if tail and not self.handle_progress(tail):
            self.append_log(tail + "\n")
        self.out_buffer = ""
        self.set_running(False)
        self._update_backup_button()

        if status == QProcess.CrashExit:
            self.status.setText("Stopped")
            if self.mode == "backup":
                self.append_log("\nBackup stopped. Running it again will pick up where it left off.\n")
            else:
                self.append_log("\nStopped.\n")
            return

        if code != 0:
            self.status.setText(f"Finished with errors (code {code})")
            self.append_log(f"\nFinished with errors (code {code}). Check the messages above.\n")
            text = self.log.toPlainText().lower()
            if self.mode == "backup":
                if "pair" in text or "trust" in text or "passwordprotected" in text or "locked" in text:
                    self.append_log("Tip: unlock the iPhone, tap Trust, then try again.\n")
                elif "usbmux" in text or "notconnected" in text or "no device" in text:
                    self.append_log("Tip: check the cable, unlock the iPhone and click Find iPhone.\n")
            elif "password" in text or "decrypt" in text:
                self.append_log("Tip: this usually means the backup password is wrong.\n")
            return

        if self.mode == "backup":
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.progress.setTextVisible(True)
            root = self.backup_root_edit.text().strip()
            picked = self.select_backup_for(self.pending_udid, root)
            self.status.setText("Backup finished")
            self.append_log(
                "\nBackup finished."
                + (" It's selected in step 2, ready to export.\n" if picked else " Pick it in step 2.\n")
            )
            b = self.current_backup()
            if picked and b and b["encrypted"] and not self.password.text():
                self.append_log("This backup is encrypted, so enter its password in step 2 before exporting.\n")
                self.password.setFocus()
            return

        if self.mode == "diagnostics":
            self.status.setText("Diagnostics done")
            return

        self.status.setText(f"Done. Saved to {self.last_export_dir}")
        self.append_log(f"\nDone. Saved to {self.last_export_dir}\n")
        self.open_btn.setEnabled(True)
        self.space_label.setText(free_space_text(self.out_edit.text()))
        if self.open_when_done.isChecked():
            self.open_export_folder()

    def cancel(self):
        if self.is_busy():
            self.process.kill()

    def open_export_folder(self):
        target = self.last_export_dir or self.out_edit.text()
        if target and Path(target).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))


def attach_stdio():
    """A windowed .exe can start with sys.stdout/stderr set to None even when the parent
    gave it pipes. Reattach them so the parent (this app's GUI) can read the output."""
    for name, fd, std_id in (("stdout", 1, -11), ("stderr", 2, -12)):
        if getattr(sys, name) is not None:
            continue
        stream = None
        try:
            os.fstat(fd)
            stream = open(fd, "w", encoding="utf-8", errors="replace", closefd=False, buffering=1)
        except OSError:
            if os.name == "nt":
                try:
                    import ctypes
                    import msvcrt

                    handle = ctypes.windll.kernel32.GetStdHandle(std_id)
                    if handle not in (0, -1, None):
                        new_fd = msvcrt.open_osfhandle(handle, os.O_WRONLY)
                        stream = open(new_fd, "w", encoding="utf-8", errors="replace", buffering=1)
                except Exception:
                    stream = None
        setattr(sys, name, stream or open(os.devnull, "w"))


def run_pymobiledevice3(args: list[str]) -> int:
    """Run the bundled pymobiledevice3 command line (used by the .exe when started with PMD3_FLAG)."""
    attach_stdio()
    sys.argv = ["pymobiledevice3"] + args
    from pymobiledevice3.__main__ import main as pmd3_main

    try:
        pmd3_main()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return 0


def self_test() -> int:
    """Quick check that the build has everything it needs. Used by the release build."""
    attach_stdio()
    ok = True
    exporter = find_exporter()
    print(f"{APP_NAME} {APP_VERSION}")
    print(f"imessage-exporter: {exporter or 'NOT FOUND'}")
    ok &= bool(exporter)
    if exporter:
        out = subprocess.run([exporter, "-V"], capture_output=True, text=True, timeout=30)
        print(f"  version: {(out.stdout or out.stderr).strip()}")
        ok &= out.returncode == 0
    cmd = pymobiledevice3_command()
    print(f"pymobiledevice3: {cmd}")
    ok &= bool(cmd)
    if cmd:
        out = subprocess.run(cmd + ["backup2", "--help"], capture_output=True, text=True, timeout=120)
        help_ok = out.returncode == 0 and "backup" in out.stdout.lower()
        print(f"  backup2 --help: {'ok' if help_ok else 'FAILED'}")
        if not help_ok:
            print(out.stdout[-2000:], out.stderr[-2000:])
        ok &= help_ok
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow()
    print(f"window: {window.windowTitle()}")
    window.close()
    print("SELF TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == PMD3_FLAG:
        sys.exit(run_pymobiledevice3(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        sys.exit(self_test())
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    if icon_path().exists():
        app.setWindowIcon(QIcon(str(icon_path())))
    window = MainWindow()
    window.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
