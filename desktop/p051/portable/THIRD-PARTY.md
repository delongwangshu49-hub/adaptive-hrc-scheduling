# Third-party components

The workbench code is under the project's MIT license. The package includes unmodified third-party runtime components. Python extensions, Qt DLLs and plugins are separate files in `app/.venv/Scripts/Lib/site-packages`, so compatible builds can be swapped in place. The workbench imposes no restriction on modification, replacement or reverse engineering for debugging changes to LGPL libraries. Isaac Sim, the Omniverse Kit SDK and NVIDIA's runtime assets are installed separately by the user.

| Component | Notices and corresponding upstream source |
| --- | --- |
| CPython 3.12.13 | `app/.venv/Scripts/LICENSE.txt`. [CPython tag](https://github.com/python/cpython/tree/v3.12.13), [Windows build 20260807](https://github.com/astral-sh/python-build-standalone/releases/tag/20260807). |
| PySide6 and Shiboken 6.12.0, Qt 6.12.0 | [Qt for Python 6.12.0](https://github.com/qtproject/pyside-pyside-setup/tree/v6.12.0), [Qt 6.12.0 source archive](https://download.qt.io/official_releases/qt/6.12/6.12.0/single/qt-everywhere-src-6.12.0.tar.xz). LGPL/GPL texts are in `licenses/qt`. Wheel notices and metadata are in `app/.venv/Scripts/Lib/site-packages/*.dist-info`. |
| Qt WebEngine and Qt PDF Python wheels 6.12.0.140 | [Qt WebEngine 6.140.0 source archive](https://download.qt.io/online/qtsdkrepository/all_os/extensions/qtwebengine/6120/61400/src_doc_examples/extensions.qtwebengine.6120.61400.src/6.12.0-0-202609281005qtwebengine-everywhere-src-6.140.0.tar.xz), [Qt WebEngine and Chromium licenses](https://doc.qt.io/qt-6/qtwebengine-licensing.html). |
| React, React DOM, Scheduler and TanStack Virtual | MIT notices in `licenses/web`. App frontend sources and `package-lock.json` are in `app/desktop/p051/web`. |
| OR-Tools and Python dependencies | Wheel notices and exact installed versions are in `app/.venv/Scripts/Lib/site-packages/*.dist-info`. |
