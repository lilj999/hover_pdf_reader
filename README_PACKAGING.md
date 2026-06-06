# Simple PDF Reader 打包说明

## 1. 推荐交付方式

建议优先使用 `onedir` 绿色版：

- 启动速度通常比 `onefile` 更稳定；
- Qt/PySide6 插件、PyMuPDF 动态库更容易完整带上；
- 便于排查缺 DLL、缺插件等问题；
- 可以直接压缩 `dist\SimplePDFReader` 发给用户。

`onefile` 单文件也可以做，但首次启动通常会先解压到临时目录，速度可能慢一些。

## 2. 构建绿色版 portable

在项目目录打开 PowerShell 或 CMD：

```bat
build_portable.bat
```

生成目录：

```text
dist\SimplePDFReader\
  SimplePDFReader.exe
  _internal\...
```

把整个 `dist\SimplePDFReader` 文件夹压缩成 zip，就是绿色版。

## 3. 构建单文件 exe

```bat
build_onefile.bat
```

生成文件：

```text
dist\SimplePDFReader.exe
```

注意：单文件版启动可能比绿色版慢。

## 4. 构建安装包

先安装 Inno Setup 6，然后执行：

```bat
build_installer.bat
```

生成文件：

```text
installer\SimplePDFReader_Setup_1.0.0.exe
```

也可以手动执行：

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

## 5. 如果打包后运行报错

先用 robust 脚本重新打包：

```bat
build_portable_robust.bat
```

它会显式收集 PySide6 和 PyMuPDF/fitz 相关资源，包会更大，但兼容性更好。

## 6. 常见问题

### 双击没有反应

用 CMD 启动 exe 查看错误：

```bat
cd dist\SimplePDFReader
SimplePDFReader.exe
```

也可以临时把 `--windowed` 改成 `--console` 重新打包，方便看日志。

### 提示 Qt platform plugin windows 找不到

使用 `build_portable_robust.bat` 重新打包。

### 提示 fitz / PyMuPDF 找不到

使用 `build_portable_robust.bat` 重新打包，或检查虚拟环境中是否能正常执行：

```bat
python pdf_reader.py
```

### 想加图标

准备一个 `app.ico`，将 PyInstaller 命令加上：

```bat
--icon app.ico
```

并在 `installer.iss` 的 `[Setup]` 中增加：

```ini
SetupIconFile=app.ico
```
