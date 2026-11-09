# Build on Windows; PyInstaller does not cross-compile Windows executables.
from pathlib import Path

root = Path(SPECPATH)
a = Analysis([str(root / 'scripts' / 'launch.py')], pathex=[str(root / 'src')],
             binaries=[], datas=[], hiddenimports=['xlrd', 'openpyxl'],
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='EMS Event Processor',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='EMS Event Processor')
