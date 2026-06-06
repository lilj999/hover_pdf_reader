# 📄 简洁专业 PDF 阅读器

一款基于 **Python + PySide6 + PyMuPDF** 的桌面 PDF 阅读器，提供 **“链接悬浮预览”** 等高效阅读体验。

> 🎯 主要亮点：**鼠标悬停即可预览内部链接的目标页**，无需点击跳转再返回，大幅提升文献阅读效率。

## ✨ 功能一览

- 📖 打开 PDF，翻页（上一页/下一页/页码跳转）
- 🔍 放大 / 缩小 / 适应宽度
- 🔗 **PDF 内部链接悬浮预览目标页**（核心特色）
- 🌐 外部 URL 悬浮显示链接地址，点击用系统浏览器打开
- ⏪ 返回上一次跳转位置
- 🖼️ 页面图片悬浮放大预览
- 📋 鼠标框选Ctrl+C复制文本

## 🖼️ 演示
- 暂无。


## 🚀 快速开始

### 环境要求
- Python 3.9 或更高版本

### 安装
```bash
git clone https://github.com/lilj999/simple_pdf_reader.git
cd simple_pdf_reader

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows PowerShell/CMD
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

## 运行

```bash
python pdf_reader.py
```

也可以直接打开指定文件：

```bash
python pdf_reader.py D:\path\to\file.pdf
```


## 说明

1. PDF 内部跳转依赖 PDF 本身是否包含 link annotation。
2. “图片悬浮预览”识别的是当前页面中的图片对象，不是普通截图中的视觉内容。
3. PDF 中类似“见图 3-2”的纯文本引用，如果没有被制作为 PDF 超链接，程序无法可靠知道它指向哪张图；需要额外做版面语义解析或建立图表索引。


# PDF Reader 
Run:
```bash
pip install PySide6 PyMuPDF
python pdf_reader.py
```
