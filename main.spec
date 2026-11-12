# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：桌面智能监控回答程序（单文件、无控制台、仅必要依赖）
# 构建方式见 build_exe.bat；产物 dist/screen_answerer.exe

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # pystray 在无控制台/冻结环境下需显式指定 Windows 后端
        'pystray._win32',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # ---- 标准库中本项目确定不用的重组件 ----
        'numpy', 'scipy', 'pandas', 'matplotlib',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx',
        'IPython', 'jedi', 'pytest', 'setuptools', 'pkg_resources',
        'unittest', 'pydoc_data', 'distutils',
        # ---- 网络库中未用到的部分 ----
        'requests_oauthlib', 'socks',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='screen_answerer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                     # 已确认不使用 UPX（规避杀软误报）
    upx_exclude=[],
    runtime_tmpdir=None,           # onefile：运行时解压到临时目录
    console=False,                 # 托盘程序,无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
    version='assets/version_info.txt',
)
