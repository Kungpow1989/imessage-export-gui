iMessage Export
===============

Back up an iPhone to this PC and save its iMessages and texts as web pages
or text files you can read, search and print.

Getting started
---------------
1. Double-click "iMessage Export.exe".
   If Windows says "Windows protected your PC", click More info, then
   Run anyway. This appears because the app isn't code-signed.

2. You need the Apple Devices app (free, Microsoft Store) or iTunes.
   You don't have to open it. It just installs the iPhone USB driver.

3. Plug in the iPhone, unlock it, and tap Trust if it asks.

4. In the app:
   Step 1  Click Find iPhone, then Back up now. Enter your passcode on the
           phone when it asks. The first backup can take a while.
   Step 2  The new backup is picked for you. If you turned on encrypted
           backups, type that password.
   Step 3  Choose HTML or text, attachments, dates, and people.
   Step 4  Choose where to save, then click Export.

Keep all the files in this folder together. The app needs them.

Optional: to convert HEIC photos to JPEG, and audio and video to common
formats, install ImageMagick and ffmpeg. In a terminal:
    winget install ImageMagick.ImageMagick Gyan.FFmpeg

More help and updates: https://github.com/Kungpow1989/imessage-export-gui

Credits
-------
The message export is done by imessage-exporter by Christopher Sardegna
(https://github.com/ReagentX/imessage-exporter). Backups are made with
pymobiledevice3 (https://github.com/doronz88/pymobiledevice3).
See THIRD-PARTY-NOTICES.txt and LICENSE.txt.
