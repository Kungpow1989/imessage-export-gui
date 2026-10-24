Third-party software
====================

iMessage Export is a front end. The real work is done by these open source
projects, and the Windows release includes them.

imessage-exporter
-----------------
By Christopher Sardegna (ReagentX) and contributors.
https://github.com/ReagentX/imessage-exporter

Reads the Messages database in an iPhone backup and exports it to HTML or
text. The release includes the unmodified Windows build of version
{IMESSAGE_EXPORTER_VERSION} as imessage-exporter.exe.

License: GNU General Public License v3.0 (GPL-3.0-only)
Source code for this exact version:
https://github.com/ReagentX/imessage-exporter/tree/{IMESSAGE_EXPORTER_VERSION}

pymobiledevice3
---------------
By doronz88, matan1008 and contributors.
https://github.com/doronz88/pymobiledevice3

Talks to the iPhone over USB and makes the backup. Bundled inside the .exe.

License: GNU General Public License v3.0 or later
Source code: https://github.com/doronz88/pymobiledevice3

PySide6 (Qt for Python)
-----------------------
By The Qt Company.
https://doc.qt.io/qtforpython/

The window, buttons and dialogs. Bundled inside the .exe.

License: GNU Lesser General Public License v3.0
Source code: https://code.qt.io/cgit/pyside/pyside-setup.git/

Python and other libraries
--------------------------
The .exe contains the Python runtime (PSF License) and the libraries that
pymobiledevice3 and PySide6 depend on, packaged with PyInstaller. Each keeps
its own license, which you can find on its PyPI page.

Full license text
-----------------
The GNU GPL v3.0 is in LICENSE.txt next to this file.
