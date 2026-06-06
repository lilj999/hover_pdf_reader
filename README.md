# Choose Your Language / 选择语言

[English (README.md)](README.md) | [中文 (README_zh.md)](README_zh.md)

# 📄 Simple Professional PDF Reader

A desktop PDF reader built with **Python + PySide6 + PyMuPDF**, designed for efficient reading with **link hover previews**.

> 🎯 Key benefit: **hover over internal PDF links to preview the target page without clicking**, so you can read papers faster without jumping back and forth.

## ✨ Features

- 📖 Open PDF files and navigate pages (previous/next/page jump)
- 🔍 Zoom in / zoom out / fit width
- 🔗 **Hover preview for internal PDF links** (core feature)
- 🌐 External URLs show the link address on hover and open in the system browser when clicked
- ⏪ Return to the previous jump location
- 🖼️ Hover preview for page images
- 📋 Select text with mouse and press Ctrl+C to copy

## 🖼️ Demo
- Not available yet.

## 🚀 Quick Start

### Requirements
- Python 3.9 or newer

### Install
```bash
git clone https://github.com/lilj999/hover_pdf_reader.git
cd hover_pdf_reader

python -m venv .venv
.venv\Scripts\activate      # Windows PowerShell/CMD
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

## Run

```bash
python pdf_reader.py
```

You can also open a PDF file directly:

```bash
python pdf_reader.py D:\path\to\file.pdf
```

## Notes

1. Internal PDF navigation depends on whether the PDF contains link annotations.
2. "Image hover preview" detects actual image objects on the current page, not visual content inside regular screenshots.
3. For plain text references like "see Figure 3-2", if they are not created as PDF hyperlinks, the program cannot reliably determine the target image without extra layout semantics or a figure/table index.

## PDF Reader

Run:
```bash
pip install PySide6 PyMuPDF
python pdf_reader.py
```
