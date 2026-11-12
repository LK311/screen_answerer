@echo off
rem 一键打包脚本：桌面智能监控回答程序 -> dist\screen_answerer.exe（单文件、无控制台、约 20MB）
rem
rem 前置（首次构建执行一次）：
rem   "D:\soft_install_path\anaconda3\envs\labelpaw\python.exe" -m venv .build_venv
rem   .build_venv\Scripts\pip install mss Pillow requests keyboard pystray pyinstaller
rem
rem 用法：双击运行,或在命令行执行 build_exe.bat

setlocal
cd /d "%~dp0"

rem conda venv 不自带 conda 的运行时 DLL（ffi-8/libssl/libcrypto/zlib）,
rem 打包时必须让 PyInstaller 依赖分析能找到它们,否则 _ctypes 导入即崩
set "PATH=D:\soft_install_path\anaconda3\envs\labelpaw\Library\bin;%PATH%"

set VENV_PY=.build_venv\Scripts\python.exe
if not exist "%VENV_PY%" (
    echo [错误] 未找到构建虚拟环境 .build_venv,请先按文件头注释初始化
    pause
    exit /b 1
)

echo [1/2] 安装/校验构建依赖...
"%VENV_PY%" -m pip install --quiet mss Pillow requests keyboard pystray pyinstaller || goto :fail

echo [2/2] PyInstaller 打包中...
"%VENV_PY%" -m PyInstaller main.spec --noconfirm --clean || goto :fail

echo.
echo 打包完成: dist\screen_answerer.exe
dir dist\screen_answerer.exe | find "screen_answerer"
echo 部署提示: settings.json 需与 exe 放在同一目录（无则首次启动自动生成默认配置）
pause
exit /b 0

:fail
echo [错误] 打包失败,请检查上方日志
pause
exit /b 1
