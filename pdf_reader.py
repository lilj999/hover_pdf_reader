# -*- coding: utf-8 -*-
"""
Simple Professional PDF Reader

版本：v9 - 科研阅读增强版：导航、搜索、高亮、书签、笔记、阅读进度恢复。

功能：
- 打开 PDF
- 连续跨页滚动阅读
- Adobe Reader 风格简洁工具栏
- 页码跳转、缩放、适应宽度
- PDF 内部/外部链接悬浮预览
- 点击内部链接跳转，点击外部链接打开浏览器
- 返回上一次跳转位置
- 页面图片对象悬浮放大预览
- 大尺寸悬浮预览 / 右侧预览栏
- 左侧目录/页码/搜索/书签/笔记面板
- 全文搜索与命中高亮
- 每篇论文阅读进度、缩放、书签和笔记自动保存

依赖：
    pip install PySide6 PyMuPDF
"""

from __future__ import annotations

import os
import sys
import re
import html
import json
import webbrowser
from dataclasses import dataclass
from typing import Optional, List, Tuple
from pathlib import Path

import fitz  # PyMuPDF
from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QSize, QTimer
from PySide6.QtGui import QAction, QColor, QBrush, QCursor, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QInputDialog,
    QMenu,
    QMenuBar,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog


@dataclass
class LinkRegion:
    """PDF 链接区域。bbox 使用 PDF 页面坐标，单位 point。"""

    bbox: fitz.Rect
    kind: int
    page: Optional[int] = None
    to: Optional[fitz.Point] = None
    uri: Optional[str] = None
    raw: Optional[dict] = None


@dataclass
class ImageRegion:
    """PDF 图片区域。bbox 使用 PDF 页面坐标。"""

    bbox: fitz.Rect
    pixmap: QPixmap
    ext: str = "image"


class PreviewPopup(QFrame):
    """鼠标悬浮大尺寸预览窗口。"""

    def __init__(self) -> None:
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName("PreviewPopup")
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet(
            """
            QFrame#PreviewPopup {
                background: #ffffff;
                border: 1px solid #b8c0cc;
                border-radius: 9px;
            }
            QLabel#PreviewTitle {
                font-weight: 600;
                font-size: 13px;
                color: #1f2937;
                padding: 8px 10px 4px 10px;
            }
            QLabel#PreviewText {
                color: #374151;
                padding: 4px 10px 10px 10px;
            }
            QLabel#PreviewImage {
                padding: 4px 10px 10px 10px;
            }
            """
        )
        self._title = QLabel()
        self._title.setObjectName("PreviewTitle")
        self._title.setWordWrap(True)
        self._image = QLabel()
        self._image.setObjectName("PreviewImage")
        self._image.setAlignment(Qt.AlignCenter)
        self._text = QPlainTextEdit()
        self._text.setObjectName("PreviewText")
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._text.setFrameStyle(QFrame.NoFrame)
        self._text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._text.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._title)
        layout.addWidget(self._image)
        layout.addWidget(self._text)
        self.hide()

    def show_text(self, title: str, text: str, global_pos: QPoint) -> None:
        self._title.setText(title)
        self._image.clear()
        self._image.hide()
        self._text.setPlainText(text)
        self._text.show()
        self.adjustSize()
        self._move_near_cursor(global_pos)
        self.show()

    # 将默认最大尺寸提升，以便在弹出预览时显示更大的图片
    def show_image(self, title: str, pixmap: QPixmap, global_pos: QPoint, max_size: QSize = QSize(960, 720)) -> None:
        self._title.setText(title)
        if pixmap.width() > max_size.width() or pixmap.height() > max_size.height():
            pixmap = pixmap.scaled(max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._image.setPixmap(pixmap)
        self._image.show()
        self._text.clear()
        self._text.hide()
        self.adjustSize()
        self._move_near_cursor(global_pos)
        self.show()

    def _move_near_cursor(self, global_pos: QPoint) -> None:
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        x = global_pos.x() + 20
        y = global_pos.y() + 20
        if available:
            if x + self.width() > available.right():
                x = global_pos.x() - self.width() - 20
            if y + self.height() > available.bottom():
                y = global_pos.y() - self.height() - 20
        self.move(max(0, x), max(0, y))


class PreviewPanel(QFrame):
    """右侧固定预览栏。"""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("PreviewPanel")
        # 允许预览栏完全收起，最小宽度设为 0，最大宽度保持 520
        self.setMinimumWidth(0)
        # 扩大预览栏最大宽度，便于显示更宽内容
        self.setMaximumWidth(800)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet(
            """
            QFrame#PreviewPanel {
                background: #f8fafc;
                border-left: 1px solid #d3d8e0;
            }
            QLabel#PanelTitle {
                font-size: 14px;
                font-weight: 700;
                color: #111827;
                padding: 10px 12px 6px 12px;
            }
            QLabel#PanelHint {
                color: #6b7280;
                padding: 0 12px 8px 12px;
            }
            QLabel#PanelImage {
                background: #ffffff;
                border: 1px solid #d6dbe3;
                border-radius: 6px;
                padding: 6px;
                margin: 0 10px 8px 10px;
            }
            QLabel#PanelText {
                color: #374151;
                background: #ffffff;
                border: 1px solid #d6dbe3;
                border-radius: 6px;
                padding: 10px;
                margin: 0 10px 8px 10px;
            }
            """
        )
        self._title = QLabel("预览")
        self._title.setObjectName("PanelTitle")
        self._title.setWordWrap(True)
        self._hint = QLabel("鼠标悬浮在 PDF 链接或图片上，可在这里查看更大的预览。")
        self._hint.setObjectName("PanelHint")
        self._hint.setWordWrap(True)
        self._image = QLabel()
        self._image.setObjectName("PanelImage")
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._image.hide()
        self._text = QPlainTextEdit()
        self._text.setObjectName("PanelText")
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._text.setFrameStyle(QFrame.NoFrame)
        self._text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._text.hide()
        self._text.setObjectName("PanelText")
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._text.setFrameStyle(QFrame.NoFrame)
        self._text.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._title)
        layout.addWidget(self._hint)
        layout.addWidget(self._image, 1)
        layout.addWidget(self._text, 1)
        layout.addStretch(1)

    def show_text(self, title: str, text: str) -> None:
        self._title.setText(title)
        self._hint.setText("单击可执行该链接动作。按 Ctrl+C 可复制文本。")
        self._image.clear()
        self._image.hide()
        self._text.setPlainText(text)
        self._text.show()

    def show_image(self, title: str, pixmap: QPixmap) -> None:
        self._title.setText(title)
        self._hint.setText("单击链接可跳转；按 Alt+← 或工具栏“返回”可回到原阅读位置。")
        # 根据预览栏实际宽度动态计算更大的显示尺寸，确保图片清晰可见
        max_w = max(400, self.width() - 20)
        max_h = max(600, self.height() - 60)
        if pixmap.width() > max_w or pixmap.height() > max_h:
            pixmap = pixmap.scaled(QSize(max_w, max_h), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._image.setPixmap(pixmap)
        self._image.setMinimumHeight(0)
        self._image.setMaximumHeight(max_h + 18)
        self._image.show()
        self._text.clear()
        self._text.hide()
        self.setFocus(Qt.OtherFocusReason)

    def clear_preview(self) -> None:
        self._title.setText("预览")
        self._hint.setText("鼠标悬浮在 PDF 链接或图片上，可在这里查看更大的预览。")
        self._image.clear()
        self._image.hide()
        self._text.clear()
        self._text.hide()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
            if self._image.isVisible() and self._image.pixmap() and not self._image.pixmap().isNull():
                QApplication.clipboard().setPixmap(self._image.pixmap())
                self._hint.setText("图片已复制到剪贴板")
                event.accept()
                return
        super().keyPressEvent(event)


class PageView(QLabel):
    """显示单页 PDF，并负责鼠标命中链接/图片区域。"""

    def __init__(self, page_index: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.page_index = page_index
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setObjectName("PageView")
        self.setFocusPolicy(Qt.StrongFocus)
        self.page_rect = fitz.Rect(0, 0, 1, 1)
        self.render_scale = 1.0
        self.links: List[LinkRegion] = []
        self.images: List[ImageRegion] = []
        self.hover_link: Optional[LinkRegion] = None
        self.hover_image: Optional[ImageRegion] = None
        self.preview = PreviewPopup()
        self._preview_key: Optional[Tuple[str, int]] = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(140)
        self._preview_timer.timeout.connect(self._show_current_preview)
        self.main_window: Optional["PdfReaderWindow"] = None
        self._selection_origin: Optional[QPoint] = None
        self._selection_rect: Optional[QRect] = None
        self._selecting = False
        self._pressed_link: Optional[LinkRegion] = None
        self.search_highlights: List[fitz.Rect] = []
        self.current_search_rect: Optional[fitz.Rect] = None
        # 用户自定义高亮列表，元素为 (fitz.Rect, QColor)
        self.user_highlights: List[Tuple[fitz.Rect, QColor]] = []

    def set_page_content(
        self,
        pixmap: QPixmap,
        page_rect: fitz.Rect,
        render_scale: float,
        links: List[LinkRegion],
        images: List[ImageRegion],
    ) -> None:
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.page_rect = page_rect
        self.render_scale = render_scale
        self.links = links
        self.images = images
        self.hover_link = None
        self.hover_image = None
        self._preview_key = None
        self.preview.hide()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        pos = event.position().toPoint()
        if self._selecting and self._selection_origin is not None:
            self._selection_rect = QRect(self._selection_origin, pos).normalized()
            self.setCursor(Qt.IBeamCursor)
            self._preview_timer.stop()
            self.preview.hide()
            self._preview_key = None
            self._update_selection_preview()
            self.update()
            return

        page_point = self._widget_to_page_point(pos)
        link = self._hit_link(page_point)
        image = None if link else self._hit_image(page_point)

        changed = (link is not self.hover_link) or (image is not self.hover_image)
        self.hover_link = link
        self.hover_image = image

        if link or image:
            self.setCursor(Qt.PointingHandCursor)
            if changed:
                self._preview_key = self._make_preview_key(link, image)
                self._preview_timer.start()
        else:
            self.setCursor(Qt.ArrowCursor)
            self._preview_timer.stop()
            self.preview.hide()
            self._preview_key = None
            if self.main_window:
                self.main_window.clear_preview_if_needed()

        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self.hover_link = None
        self.hover_image = None
        self._preview_timer.stop()
        self.preview.hide()
        self.setCursor(Qt.ArrowCursor)
        if self.main_window:
            self.main_window.clear_preview_if_needed()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            # 鼠标左键点击时的行为分两种：
            # 1. 如果点击在图片区域，则保持原有的框选逻辑，允许用户拖拽选择图片或文字块。
            # 2. 否则尝试在点击位置选取单个单词，类似 Adobe Reader 的“单词选取”。
            self.setFocus(Qt.MouseFocusReason)
            click_pos = event.position().toPoint()
            page_point = self._widget_to_page_point(click_pos)
            # 首先检查是否点中了图片，若是则进入矩形选取模式。
            if self._hit_image(page_point):
                self._selection_origin = click_pos
                self._selection_rect = QRect(self._selection_origin, self._selection_origin)
                self._selecting = True
                self._pressed_link = self._hit_link(page_point)
                return
            # 非图片区域：尝试选取光标所在的单词。
            word_rect = self._find_word_rect(page_point)
            if word_rect:
                # 将 PDF 坐标转换为 widget 坐标后直接设为选区。
                self._selection_rect = self._page_rect_to_widget_rect(word_rect).toRect()
                self._selecting = False
                self._pressed_link = None
                # 立即更新复制预览（如果预览面板可见）。
                self._update_selection_preview()
                self.update()
                return
            # 若未找到单词，则回退到原有的空选区行为，保持后续的拖拽可创建矩形选区。
            self._selection_origin = click_pos
            self._selection_rect = QRect(self._selection_origin, self._selection_origin)
            self._selecting = True
            self._pressed_link = self._hit_link(page_point)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._selecting:
            self._selecting = False
            if self._selection_rect and self._selection_rect.width() <= 4 and self._selection_rect.height() <= 4:
                if self._pressed_link and self.main_window:
                    self.main_window.activate_link(self._pressed_link)
                self._selection_rect = None
            self._pressed_link = None
            self.update()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
            self._copy_selection_text()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:  # type: ignore[override]
        menu = QMenu(self)
        # 复制文本
        copy_action = QAction("复制文本", self)
        copy_action.triggered.connect(self._copy_selection_text)
        copy_action.setEnabled(bool(self._selection_rect and not self._selection_rect.isEmpty()))
        menu.addAction(copy_action)
        # 高亮颜色子菜单（仅在有选区时显示）
        if self._selection_rect and not self._selection_rect.isEmpty():
            color_menu = QMenu("高亮颜色", self)
            colors = {
                "黄色": QColor(255, 255, 0, 80),
                "绿色": QColor(0, 255, 0, 80),
                "粉色": QColor(255, 192, 203, 80),
                "蓝色": QColor(135, 206, 250, 80),
            }
            for name, qcol in colors.items():
                act = QAction(name, self)
                # 使用默认参数捕获颜色
                act.triggered.connect(lambda _, c=qcol: self._apply_highlight(c))
                color_menu.addAction(act)
            menu.addMenu(color_menu)
        menu.exec(event.globalPos())

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.search_highlights:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 230, 0, 82)))
            for rect in self.search_highlights:
                painter.drawRect(self._page_rect_to_widget_rect(rect))
            if self.current_search_rect is not None:
                painter.setBrush(QBrush(QColor(255, 128, 0, 96)))
                painter.drawRect(self._page_rect_to_widget_rect(self.current_search_rect))

        if self._selection_rect and not self._selection_rect.isEmpty():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(Qt.black, 1, Qt.DashLine))
            painter.drawRect(self._selection_rect)

        if self.hover_link:
            rect = self._page_rect_to_widget_rect(self.hover_link.bbox)
            painter.setPen(QPen(Qt.blue, 2, Qt.SolidLine))
            painter.drawRoundedRect(rect, 4, 4)

        if self.hover_image:
            rect = self._page_rect_to_widget_rect(self.hover_image.bbox)
            painter.setPen(QPen(Qt.darkGray, 2, Qt.DashLine))
            painter.drawRoundedRect(rect, 4, 4)

    def _copy_selection_text(self) -> None:
        text = self._get_selected_text()
        if text:
            QApplication.clipboard().setText(text)
            if self.main_window:
                self.main_window.status.showMessage("已复制选中文本到剪贴板", 2000)
        else:
            if self.main_window:
                self.main_window.status.showMessage("没有可复制的选中文本", 2000)

    def _apply_highlight(self, color: QColor) -> None:
        """将当前选区添加为高亮并通知主窗口记录。"""
        if not self._selection_rect or self._selection_rect.isEmpty():
            return
        # 将 widget 坐标转换回 PDF 坐标
        top_left = self._widget_to_page_point(self._selection_rect.topLeft())
        bottom_right = self._widget_to_page_point(self._selection_rect.bottomRight())
        rect = fitz.Rect(top_left, bottom_right)
        # 保存到本页面的高亮列表
        self.user_highlights.append((rect, color))
        self.update()
        # 通知主窗口持久化
        if self.main_window:
            self.main_window.record_highlight(self.page_index, rect, color)

    def _get_selected_text(self) -> str:
        if not self._selection_rect or self._selection_rect.isEmpty() or not self.main_window or not self.main_window.doc:
            return ""
        page = self.main_window.doc.load_page(self.page_index)
        top_left = self._widget_to_page_point(self._selection_rect.topLeft())
        bottom_right = self._widget_to_page_point(self._selection_rect.bottomRight())
        selection_rect = fitz.Rect(top_left, bottom_right)
        words = page.get_text("words")
        selected: List[Tuple[float, float, str]] = []
        for item in words:
            if len(item) < 5:
                continue
            x0, y0, x1, y1, text = item[0], item[1], item[2], item[3], item[4]
            word_rect = fitz.Rect(x0, y0, x1, y1)
            if word_rect.intersects(selection_rect):
                selected.append((y0, x0, text))
        if not selected:
            return ""
        selected.sort()
        return " ".join(word for _, _, word in selected).strip()

    def _update_selection_preview(self) -> None:
        if not self.main_window or not self.main_window.is_preview_panel_visible():
            return
        text = self._get_selected_text()
        if text:
            self.main_window.show_preview_text("选中文本预览", text)


    def set_search_highlights(self, rects: List[fitz.Rect], current_rect: Optional[fitz.Rect] = None) -> None:
        self.search_highlights = rects
        self.current_search_rect = current_rect
        self.update()

    def clear_search_highlights(self) -> None:
        self.search_highlights = []
        self.current_search_rect = None
        self.update()

    def _widget_to_page_point(self, pos: QPoint) -> fitz.Point:
        return fitz.Point(pos.x() / self.render_scale, pos.y() / self.render_scale)

    def _page_rect_to_widget_rect(self, rect: fitz.Rect) -> QRectF:
        return QRectF(
            rect.x0 * self.render_scale,
            rect.y0 * self.render_scale,
            rect.width * self.render_scale,
            rect.height * self.render_scale,
        )

    def _hit_link(self, point: fitz.Point) -> Optional[LinkRegion]:
        for link in self.links:
            if link.bbox.contains(point):
                return link
        return None

    def _hit_image(self, point: fitz.Point) -> Optional[ImageRegion]:
        # 从小图到大图命中可能更符合用户直觉。
        for image in sorted(self.images, key=lambda item: item.bbox.width * item.bbox.height):
            if image.bbox.contains(point):
                return image
        return None

    def _find_word_rect(self, point: fitz.Point) -> Optional[fitz.Rect]:
        """在给定的 PDF 坐标点查找包含该点的单词矩形。

        通过访问主窗口的 ``doc`` 对象获取当前页的文字信息。
        返回 ``fitz.Rect``，若未找到则返回 ``None``。
        """
        if not self.main_window or not self.main_window.doc:
            return None
        try:
            page = self.main_window.doc.load_page(self.page_index)
            words = page.get_text("words")
            for w in words:
                if len(w) < 5:
                    continue
                x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
                word_rect = fitz.Rect(x0, y0, x1, y1)
                if word_rect.contains(point):
                    return word_rect
        except Exception:
            pass
        return None

    def _make_preview_key(self, link: Optional[LinkRegion], image: Optional[ImageRegion]) -> Optional[Tuple[str, int]]:
        if link:
            return ("link", id(link))
        if image:
            return ("image", id(image))
        return None

    def _show_current_preview(self) -> None:
        global_pos = QCursor.pos()
        if self.hover_link and self.main_window:
            link = self.hover_link
            if link.uri:
                safe_uri = html.escape(link.uri)
                text = (
                    f"<div style='max-width:620px;line-height:1.45'>{safe_uri}</div>"
                    "<div style='margin-top:8px;color:#6b7280'>单击后用系统浏览器打开</div>"
                )
                if self.main_window.is_preview_panel_visible():
                    self.main_window.show_preview_text("外部链接", text)
                else:
                    self.preview.show_text("外部链接", text, global_pos)
            elif link.page is not None:
                raw_target_y = link.to.y if link.to else None
                target_y = self.main_window.normalize_link_target_y(link.page, raw_target_y)
                source_text = self.main_window.render_link_source_text(link, self.page_index)
                display_text = self.main_window.render_link_display_text(link, self.page_index)
                link_type = self.main_window.classify_internal_link(link, self.page_index)

                if link_type == "reference":
                    title = f"文献引用预览：第 {link.page + 1} 页"
                    target_text = self.main_window.render_link_reference_text(
                        link, self.page_index, link.page, target_y
                    )
                    if source_text and target_text:
                        text = f"链接文本：{source_text}\n\n引用内容：{target_text}"
                    elif target_text:
                        text = target_text
                    elif source_text:
                        pix = self.main_window.render_page_preview(link.page, focus_y=target_y)
                        if pix:
                            image_title = f"目标页预览：第 {link.page + 1} 页（{source_text}）"
                            if self.main_window.is_preview_panel_visible():
                                self.main_window.show_preview_image(image_title, pix)
                            else:
                                self.preview.show_image(image_title, pix, global_pos, QSize(760, 560))
                            return
                        text = f"链接文本：{source_text}\n\n未能自动解析目标文献条目，单击可跳转查看。"
                    else:
                        text = "单击后跳转到目标页。"

                    if self.main_window.is_preview_panel_visible():
                        self.main_window.show_preview_text(title, text)
                    else:
                        self.preview.show_text(title, text, global_pos)
                    return

                if link_type in {"figure", "table"}:
                    title_prefix = "图目标预览" if link_type == "figure" else "表格目标预览"
                    pix = self.main_window.render_page_preview(
                        link.page,
                        focus_y=target_y,
                        source_text=display_text,
                        link_type=link_type,
                    )
                    image_title = f"{title_prefix}：第 {link.page + 1} 页"
                    if display_text:
                        image_title += f"（{display_text}）"
                    if pix:
                        if self.main_window.is_preview_panel_visible():
                            self.main_window.show_preview_image(image_title, pix)
                        else:
                            self.preview.show_image(image_title, pix, global_pos, QSize(820, 640))
                        return

                title_map = {
                    "section": "章节目标预览",
                    "equation": "公式目标预览",
                    "internal": "内部链接预览",
                }
                title = f"{title_map.get(link_type, '内部链接预览')}：第 {link.page + 1} 页"
                target_text = self.main_window.render_internal_link_target_text(
                    link.page, target_y, link_type, display_text
                )
                if target_text:
                    text = f"链接文本：{display_text or source_text or '(未提取到链接文本)'}\n\n目标内容：{target_text}\n\n单击可跳转到目标位置。"
                    if self.main_window.is_preview_panel_visible():
                        self.main_window.show_preview_text(title, text)
                    else:
                        self.preview.show_text(title, text, global_pos)
                    return

                pix = self.main_window.render_page_preview(link.page, focus_y=target_y, link_type=link_type)
                if pix:
                    image_title = title
                    if display_text or source_text:
                        image_title += f"（{display_text or source_text}）"
                    if self.main_window.is_preview_panel_visible():
                        self.main_window.show_preview_image(image_title, pix)
                    else:
                        self.preview.show_image(image_title, pix, global_pos, QSize(760, 560))
                else:
                    text = f"链接文本：{display_text or source_text or '(未提取到链接文本)'}\n\n单击后跳转到目标页。"
                    if self.main_window.is_preview_panel_visible():
                        self.main_window.show_preview_text(title, text)
                    else:
                        self.preview.show_text(title, text, global_pos)
            else:
                # 有些出版商 PDF（如 Nature/Springer）把文献引用、Fig. 引用做成
                # LINK_NAMED / named destination。PyMuPDF 的 get_links() 对这类链接
                # 往往只有 raw["nameddest"]，没有 page/to/uri。原逻辑会落到这里，
                # 只显示“PDF 链接”，看起来像预览失效。
                named_text = self.main_window.render_named_destination_preview_text(link, self.page_index)
                if named_text:
                    title = self.main_window.infer_named_destination_title(named_text)
                    if self.main_window.is_preview_panel_visible():
                        self.main_window.show_preview_text(title, named_text)
                    else:
                        self.preview.show_text(title, named_text, global_pos)
                    return

                text = "单击后尝试执行该链接动作。"
                if self.main_window.is_preview_panel_visible():
                    self.main_window.show_preview_text("PDF 链接", text)
                else:
                    self.preview.show_text("PDF 链接", text, global_pos)
        elif self.hover_image and self.main_window:
            title = f"第 {self.page_index + 1} 页图片预览"
            if self.main_window.is_preview_panel_visible():
                self.main_window.show_preview_image(title, self.hover_image.pixmap)
            else:
                self.preview.show_image(title, self.hover_image.pixmap, global_pos, QSize(840, 640))


class PageFrame(QFrame):
    """带页码标题和阴影感边框的单页外壳。"""

    def __init__(self, page_index: int, total_pages: int, page_view: PageView) -> None:
        super().__init__()
        self.page_index = page_index
        self.page_view = page_view
        self.setObjectName("PageFrame")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        title = QLabel(f"第 {page_index + 1} / {total_pages} 页")
        title.setObjectName("PageCaption")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(title)
        layout.addWidget(page_view)


class PdfReaderWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDF Reader")
        self.resize(1260, 860)
        self.doc: Optional[fitz.Document] = None
        self.file_path: Optional[str] = None
        self.current_page = 0
        self.zoom = 1.25
        self.history: List[Tuple[int, int]] = []
        self.page_views: List[PageView] = []
        self.page_frames: List[PageFrame] = []
        self._syncing_scroll = False
        self._syncing_page_spin = False
        self.references: dict = {}
        self.config_file = Path.home() / ".pdf_reader_config.json"
        self.last_file_dir = self._load_last_dir()
        self.state_file = Path.home() / ".pdf_reader_research_state.json"
        self.app_state = self._load_app_state()
        self.bookmarks: List[dict] = []
        self.notes: dict = {}
        self.note_editor_page: Optional[int] = None
        self.search_hits: List[Tuple[int, fitz.Rect, str]] = []
        self.search_index = -1
        self._pending_restore_scroll: Optional[int] = None
        # 高亮持久化结构：{page_index: [(rect_dict, rgba_tuple), ...]}
        # 高亮持久化结构：{page_index: [(rect_dict, rgba_tuple), ...]}
        self._highlights: dict[int, List[Tuple[dict, Tuple[int, int, int, int]]]] = {}


        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("ScrollContent")
        self.pages_layout = QVBoxLayout(self.scroll_content)
        self.pages_layout.setContentsMargins(28, 24, 28, 24)
        self.pages_layout.setSpacing(22)
        self.pages_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.pages_layout.addStretch(1)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_content)
        self.scroll_area.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.scroll_area.setStyleSheet("QScrollArea { background: #dfe3ea; border: none; }")
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)

        self.preview_panel = PreviewPanel()
        self.preview_panel.setVisible(True)

        self.nav_tabs = self._build_sidebar()

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(True)  # 允许预览区可拖动隐藏/显示
        self.splitter.addWidget(self.scroll_area)
        self.splitter.addWidget(self.preview_panel)
        self.splitter.setSizes([900, 360])
        # 设置拖动手柄使其可见
        self.splitter.setHandleWidth(8)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(True)  # 允许列表区可拖动隐藏/显示
        self.main_splitter.addWidget(self.nav_tabs)
        self.main_splitter.addWidget(self.splitter)
        self.main_splitter.setSizes([260, 1000])
        # 设置拖动手柄使其可见
        self.main_splitter.setHandleWidth(8)
        self.setCentralWidget(self.main_splitter)
        self.setAcceptDrops(True)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._build_menu()
        self._build_toolbar()
        self._apply_style()


    def _build_sidebar(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("NavTabs")
        tabs.setMinimumWidth(230)
        tabs.setMaximumWidth(360)

        self.outline_tree = QTreeWidget()
        self.outline_tree.setHeaderLabels(["目录", "页"])
        self.outline_tree.itemClicked.connect(self.on_outline_clicked)
        tabs.addTab(self.outline_tree, "目录")

        self.pages_list = QListWidget()
        self.pages_list.itemClicked.connect(self.on_page_item_clicked)
        tabs.addTab(self.pages_list, "页码")

        self.search_results_list = QListWidget()
        self.search_results_list.itemClicked.connect(self.on_search_result_clicked)
        tabs.addTab(self.search_results_list, "搜索")

        bookmarks_page = QWidget()
        bookmarks_layout = QVBoxLayout(bookmarks_page)
        bookmarks_layout.setContentsMargins(6, 6, 6, 6)
        self.bookmark_list = QListWidget()
        self.bookmark_list.itemClicked.connect(self.on_bookmark_clicked)
        add_btn = QPushButton("添加当前页书签")
        add_btn.clicked.connect(self.add_bookmark_current)
        del_btn = QPushButton("删除选中书签")
        del_btn.clicked.connect(self.delete_selected_bookmark)
        bookmarks_layout.addWidget(self.bookmark_list, 1)
        bookmarks_layout.addWidget(add_btn)
        bookmarks_layout.addWidget(del_btn)
        tabs.addTab(bookmarks_page, "书签")

        notes_page = QWidget()
        notes_layout = QVBoxLayout(notes_page)
        notes_layout.setContentsMargins(6, 6, 6, 6)
        self.note_title = QLabel("当前页笔记")
        self.note_title.setWordWrap(True)
        self.note_editor = QPlainTextEdit()
        self.note_editor.setPlaceholderText("在这里记录当前页想法、问题、实验结论等。")
        save_note_btn = QPushButton("保存当前页笔记")
        save_note_btn.clicked.connect(self.save_current_note)
        self.notes_list = QListWidget()
        self.notes_list.itemClicked.connect(self.on_note_item_clicked)
        notes_layout.addWidget(self.note_title)
        notes_layout.addWidget(self.note_editor, 1)
        notes_layout.addWidget(save_note_btn)
        notes_layout.addWidget(QLabel("已有笔记"))
        notes_layout.addWidget(self.notes_list, 1)
        tabs.addTab(notes_page, "笔记")
        return tabs

    def populate_navigation_panels(self) -> None:
        self.populate_outline()
        self.populate_pages_list()
        self.populate_bookmarks_list()
        self.populate_notes_list()
        self.update_note_editor_for_page(self.current_page)

    def populate_outline(self) -> None:
        self.outline_tree.clear()
        if not self.doc:
            return
        toc = []
        try:
            toc = self.doc.get_toc(simple=True)
        except Exception:
            toc = []
        if toc:
            level_items = {}
            for level, title, page_no in toc:
                item = QTreeWidgetItem([str(title), str(page_no)])
                item.setData(0, Qt.UserRole, max(0, int(page_no) - 1))
                parent = level_items.get(level - 1)
                if parent is not None:
                    parent.addChild(item)
                else:
                    self.outline_tree.addTopLevelItem(item)
                level_items[level] = item
            self.outline_tree.expandToDepth(1)
            return
        # 没有 PDF 内置目录时，按常见论文章节标题自动生成简易目录。
        heading_patterns = [
            r"^abstract\b", r"^\d+(?:\.\d+)*\s+\S+", r"^i+\.\s+\S+",
            r"^introduction\b", r"^related\s+work\b", r"^method\b", r"^methods\b",
            r"^experiments?\b", r"^evaluation\b", r"^results?\b", r"^discussion\b",
            r"^conclusion\b", r"^references\b", r"^appendix\b",
        ]
        added = set()
        for page_index in range(self.doc.page_count):
            try:
                blocks = self.doc.load_page(page_index).get_text("blocks")
            except Exception:
                continue
            for block in blocks:
                if len(block) < 5:
                    continue
                line = re.sub(r"\s+", " ", str(block[4]).strip()).strip()
                if not line or len(line) > 90:
                    continue
                lower = line.lower()
                if any(re.match(p, lower) for p in heading_patterns):
                    key = (page_index, lower)
                    if key in added:
                        continue
                    added.add(key)
                    item = QTreeWidgetItem([line, str(page_index + 1)])
                    item.setData(0, Qt.UserRole, page_index)
                    self.outline_tree.addTopLevelItem(item)
                    break

    def populate_pages_list(self) -> None:
        self.pages_list.clear()
        if not self.doc:
            return
        for i in range(self.doc.page_count):
            item = QListWidgetItem(f"第 {i + 1} 页")
            item.setData(Qt.UserRole, i)
            self.pages_list.addItem(item)

    def populate_bookmarks_list(self) -> None:
        self.bookmark_list.clear()
        for bm in self.bookmarks:
            page = int(bm.get("page", 0))
            title = bm.get("title") or f"第 {page + 1} 页"
            item = QListWidgetItem(f"{page + 1}: {title}")
            item.setData(Qt.UserRole, page)
            self.bookmark_list.addItem(item)

    def populate_notes_list(self) -> None:
        self.notes_list.clear()
        for key in sorted(self.notes, key=lambda x: int(x) if str(x).isdigit() else 10**9):
            text = str(self.notes.get(key, "")).strip()
            if not text:
                continue
            page = int(key)
            first = re.sub(r"\s+", " ", text).strip()[:48]
            item = QListWidgetItem(f"{page + 1}: {first}")
            item.setData(Qt.UserRole, page)
            self.notes_list.addItem(item)

    def on_outline_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        page = item.data(0, Qt.UserRole)
        if page is not None:
            self.scroll_to_page(int(page))

    def on_page_item_clicked(self, item: QListWidgetItem) -> None:
        page = item.data(Qt.UserRole)
        if page is not None:
            self.scroll_to_page(int(page))

    def on_bookmark_clicked(self, item: QListWidgetItem) -> None:
        page = item.data(Qt.UserRole)
        if page is not None:
            self.scroll_to_page(int(page))

    def on_note_item_clicked(self, item: QListWidgetItem) -> None:
        page = item.data(Qt.UserRole)
        if page is not None:
            self.scroll_to_page(int(page))
            self.nav_tabs.setCurrentWidget(self.note_editor.parentWidget())

    def add_bookmark_current(self) -> None:
        if not self.doc:
            return
        default_title = f"第 {self.current_page + 1} 页"
        title, ok = QInputDialog.getText(self, "添加书签", "书签名称：", text=default_title)
        if not ok:
            return
        title = title.strip() or default_title
        page = int(self.current_page)
        self.bookmarks = [bm for bm in self.bookmarks if int(bm.get("page", -1)) != page]
        self.bookmarks.append({"page": page, "title": title})
        self.bookmarks.sort(key=lambda bm: int(bm.get("page", 0)))
        self.populate_bookmarks_list()
        self._save_current_document_state()
        self.status.showMessage(f"已添加书签：{title}", 2000)

    def delete_selected_bookmark(self) -> None:
        item = self.bookmark_list.currentItem()
        if not item:
            return
        page = int(item.data(Qt.UserRole))
        self.bookmarks = [bm for bm in self.bookmarks if int(bm.get("page", -1)) != page]
        self.populate_bookmarks_list()
        self._save_current_document_state()
        self.status.showMessage("已删除书签", 2000)

    def update_note_editor_for_page(self, page_index: int) -> None:
        if not hasattr(self, "note_editor"):
            return
        self.note_editor_page = page_index
        self.note_title.setText(f"第 {page_index + 1} 页笔记")
        self.note_editor.blockSignals(True)
        self.note_editor.setPlainText(str(self.notes.get(str(page_index), "")))
        self.note_editor.blockSignals(False)

    def save_current_note(self) -> None:
        if self.note_editor_page is None:
            return
        text = self.note_editor.toPlainText().strip()
        key = str(self.note_editor_page)
        if text:
            self.notes[key] = text
        else:
            self.notes.pop(key, None)
        self.populate_notes_list()
        self._save_current_document_state()
        self.status.showMessage("笔记已保存", 2000)

    def search_document(self) -> None:
        if not self.doc:
            return
        query = self.search_edit.text().strip()
        self.search_results_list.clear()
        self.search_hits = []
        self.search_index = -1
        for view in self.page_views:
            view.clear_search_highlights()
        if not query:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for page_index in range(self.doc.page_count):
                page = self.doc.load_page(page_index)
                rects = page.search_for(query)
                for rect in rects:
                    clip = fitz.Rect(max(0, rect.x0 - 80), max(0, rect.y0 - 22), min(page.rect.width, rect.x1 + 220), min(page.rect.height, rect.y1 + 22))
                    excerpt = re.sub(r"\s+", " ", page.get_textbox(clip)).strip()
                    if not excerpt:
                        excerpt = query
                    self.search_hits.append((page_index, rect, excerpt[:180]))
        except Exception as exc:
            QMessageBox.warning(self, "搜索失败", f"全文搜索失败：\n{exc}")
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh_search_results()
        self._apply_search_highlights()
        if self.search_hits:
            self.search_index = 0
            self.goto_search_hit(0)
        self.status.showMessage(f"搜索“{query}”：{len(self.search_hits)} 处命中", 3000)

    def _refresh_search_results(self) -> None:
        self.search_results_list.clear()
        for idx, (page, rect, excerpt) in enumerate(self.search_hits):
            item = QListWidgetItem(f"第 {page + 1} 页：{excerpt}")
            item.setData(Qt.UserRole, idx)
            self.search_results_list.addItem(item)
        if self.search_hits:
            # 自动显示左列表区并切换到搜索结果标签页
            if not self.nav_tabs.isVisible():
                self.nav_tabs.setVisible(True)
                self.sidebar_action.setChecked(True)
            self.nav_tabs.setCurrentWidget(self.search_results_list)

    def _apply_search_highlights(self) -> None:
        by_page = {}
        current = self.search_hits[self.search_index] if 0 <= self.search_index < len(self.search_hits) else None
        for page, rect, _ in self.search_hits:
            by_page.setdefault(page, []).append(rect)
        for view in self.page_views:
            cur_rect = current[1] if current and current[0] == view.page_index else None
            view.set_search_highlights(by_page.get(view.page_index, []), cur_rect)

    def goto_search_hit(self, index: int) -> None:
        if not self.search_hits:
            return
        self.search_index = max(0, min(index, len(self.search_hits) - 1))
        page, rect, _ = self.search_hits[self.search_index]
        self._apply_search_highlights()
        self.search_results_list.setCurrentRow(self.search_index)
        self.scroll_to_page(page, rect.y0)

    def search_next_hit(self) -> None:
        if not self.search_hits:
            self.search_document()
            return
        self.goto_search_hit((self.search_index + 1) % len(self.search_hits))

    def search_prev_hit(self) -> None:
        if not self.search_hits:
            self.search_document()
            return
        self.goto_search_hit((self.search_index - 1) % len(self.search_hits))

    def on_search_result_clicked(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.UserRole)
        if idx is not None:
            self.goto_search_hit(int(idx))

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        
        # File 菜单
        file_menu = menubar.addMenu("文件(&F)")
        
        open_action = QAction("打开(&O)", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.open_file_dialog)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        print_action = QAction("打印(&P)", self)
        print_action.setShortcut(QKeySequence.Print)
        print_action.triggered.connect(self.print_pdf)
        file_menu.addAction(print_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 保存高亮修改（快捷键 Ctrl+S）
        save_action = QAction("保存修改(&S)", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_highlights)
        # 将保存动作放在退出前
        file_menu.insertAction(exit_action, save_action)
        
        # View 菜单
        view_menu = menubar.addMenu("查看(&V)")
        
        self.sidebar_action = QAction("左列表区(&L)", self)
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(True)
        self.sidebar_action.triggered.connect(self.toggle_sidebar)
        view_menu.addAction(self.sidebar_action)
        
        self.preview_panel_action = QAction("预览栏(&P)", self)
        self.preview_panel_action.setCheckable(True)
        self.preview_panel_action.setChecked(True)
        self.preview_panel_action.triggered.connect(self.toggle_preview_panel)
        view_menu.addAction(self.preview_panel_action)

    def toggle_sidebar(self) -> None:
        visible = self.sidebar_action.isChecked()
        self.nav_tabs.setVisible(visible)
        if visible:
            self.status.showMessage("左列表区已显示", 2000)
        else:
            self.status.showMessage("左列表区已隐藏", 2000)

    def print_pdf(self) -> None:
        if not self.doc or not self.file_path:
            QMessageBox.warning(self, "无法打印", "没有打开任何 PDF 文件。")
            return
        
        try:
            import subprocess
            import platform
            
            # 使用系统默认 PDF 阅读器的打印功能
            if platform.system() == 'Windows':
                # Windows: 使用 ShellExecute 打开打印对话框
                import ctypes
                from ctypes import wintypes
                
                OpenAsInfo = ctypes.Structure
                OpenAsInfo._fields_ = [
                    ('cbSize', wintypes.DWORD),
                    ('lpClass', wintypes.LPCWSTR),
                    ('lpAction', wintypes.LPCWSTR),
                    ('pcszFile', wintypes.LPCWSTR),
                    ('pcszClass', wintypes.LPCWSTR),
                ]
                
                try:
                    shell32 = ctypes.windll.shell32
                    oainfo = OpenAsInfo()
                    oainfo.cbSize = ctypes.sizeof(OpenAsInfo)
                    oainfo.lpAction = "print"
                    oainfo.pcszFile = self.file_path
                    shell32.OpenAsInfoW(ctypes.byref(oainfo), None, 0)
                except Exception:
                    # 备选方案：使用 AcroExch.PDFFile COM 对象或系统关联打印
                    subprocess.Popen(['explorer.exe', '/print,', self.file_path])
            elif platform.system() == 'Darwin':
                # macOS
                subprocess.Popen(['open', '-a', 'Preview', self.file_path])
            else:
                # Linux
                subprocess.Popen(['xdg-open', self.file_path])
            
            self.status.showMessage("打印对话框已打开", 2000)
        except Exception as exc:
            QMessageBox.warning(self, "打印失败", f"打印过程中出错：\n{exc}")

    def _print_to_printer(self, printer: QPrinter) -> None:
        # 这个方法已弃用，使用简化的打印方案
        pass

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏")
        toolbar.setObjectName("MainToolBar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(toolbar)

        open_action = QAction("打开", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.open_file_dialog)
        toolbar.addAction(open_action)

       

        toolbar.addSeparator()

        prev_action = QAction("上一页", self)
        prev_action.setShortcut(QKeySequence(Qt.Key_PageUp))
        prev_action.triggered.connect(self.prev_page)
        toolbar.addAction(prev_action)

        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.setFixedWidth(76)
        self.page_spin.valueChanged.connect(self.on_page_spin_changed)
        toolbar.addWidget(self.page_spin)

        self.page_count_label = QLabel("/ 0")
        self.page_count_label.setObjectName("ToolLabel")
        toolbar.addWidget(self.page_count_label)

        next_action = QAction("下一页", self)
        next_action.setShortcut(QKeySequence(Qt.Key_PageDown))
        next_action.triggered.connect(self.next_page)
        toolbar.addAction(next_action)

        toolbar.addSeparator()

        zoom_out = QAction("−", self)
        zoom_out.setShortcut(QKeySequence.ZoomOut)
        zoom_out.triggered.connect(lambda: self.change_zoom(0.85))
        toolbar.addAction(zoom_out)

        self.zoom_label = QLabel("125%")
        self.zoom_label.setObjectName("ZoomLabel")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setFixedWidth(64)
        toolbar.addWidget(self.zoom_label)

        zoom_in = QAction("+", self)
        zoom_in.setShortcut(QKeySequence.ZoomIn)
        zoom_in.triggered.connect(lambda: self.change_zoom(1.18))
        toolbar.addAction(zoom_in)

        fit_width = QAction("适合宽度", self)
        fit_width.triggered.connect(self.fit_width)
        toolbar.addAction(fit_width)

        toolbar.addSeparator()

        bookmark_action = QAction("加书签", self)
        bookmark_action.setShortcut(QKeySequence("Ctrl+B"))
        bookmark_action.triggered.connect(self.add_bookmark_current)
        toolbar.addAction(bookmark_action)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("搜索"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("关键词 ↵")
        self.search_edit.setFixedWidth(170)
        self.search_edit.returnPressed.connect(self.search_document)
        toolbar.addWidget(self.search_edit)

        search_prev = QAction("上一个", self)
        search_prev.setShortcut(QKeySequence("Shift+F3"))
        search_prev.triggered.connect(self.search_prev_hit)
        toolbar.addAction(search_prev)

        search_next = QAction("下一个", self)
        search_next.setShortcut(QKeySequence("F3"))
        search_next.triggered.connect(self.search_next_hit)
        toolbar.addAction(search_next)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("查页"))
        self.quick_page_edit = QLineEdit()
        self.quick_page_edit.setPlaceholderText("页码 ↵")
        self.quick_page_edit.setFixedWidth(90)
        self.quick_page_edit.returnPressed.connect(self.quick_jump_page)
        toolbar.addWidget(self.quick_page_edit)

        toolbar.addSeparator()

        self.back_action = QAction("← 返回", self)
        self.back_action.setShortcut(QKeySequence(Qt.ALT | Qt.Key_Left))
        self.back_action.triggered.connect(self.go_back)
        self.back_action.setEnabled(False)
        toolbar.addAction(self.back_action)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #f6f7f9; }
            QToolBar#MainToolBar {
                background: #f3f4f6;
                border-top: 1px solid #ffffff;
                border-bottom: 1px solid #bfc5cf;
                spacing: 5px;
                padding: 4px 7px;
            }
            QToolButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 5px 9px;
                color: #202124;
            }
            QToolButton:hover { background: #ffffff; border-color: #b8bec9; }
            QToolButton:pressed { background: #e6eaf0; border-color: #aeb6c2; }
            QToolButton:checked { background: #e8f0fe; border-color: #8ab4f8; }
            QToolButton:disabled { color: #9ca3af; }
            QSpinBox, QLineEdit {
                background: #ffffff;
                border: 1px solid #aeb6c2;
                border-radius: 3px;
                padding: 4px 6px;
            }
            QLabel#ToolLabel, QLabel#ZoomLabel {
                color: #202124;
                padding: 0 5px;
            }
            QLabel#ZoomLabel {
                background: #ffffff;
                border: 1px solid #aeb6c2;
                border-radius: 3px;
                padding: 4px 6px;
            }
            QWidget#ScrollContent { background: #dfe3ea; }
            QFrame#PageFrame {
                background: transparent;
            }
            QLabel#PageCaption {
                color: #4b5563;
                padding: 0 2px;
                font-size: 12px;
            }
            QLabel#PageView {
                background: #ffffff;
                border: 1px solid #b8c0cc;
            }
            QStatusBar { background: #f8fafc; color: #4b5563; border-top: 1px solid #d3d8e0; }
            QSplitter::handle { background: #c9ced6; width: 1px; }
            QTabWidget#NavTabs::pane { border-right: 1px solid #c9ced6; background: #f8fafc; }
            QTreeWidget, QListWidget, QPlainTextEdit {
                background: #ffffff;
                border: 1px solid #d3d8e0;
                border-radius: 4px;
            }
            QPushButton {
                background: #ffffff;
                border: 1px solid #aeb6c2;
                border-radius: 4px;
                padding: 5px 8px;
            }
            QPushButton:hover { background: #f3f4f6; }
            """
        )

    def open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开 PDF", self.last_file_dir, "PDF 文件 (*.pdf)")
        if path:
            self.open_pdf(path)

    def open_pdf(self, path: str) -> None:
        try:
            doc = fitz.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "无法打开 PDF", f"文件打开失败：\n{exc}")
            return

        if doc.page_count <= 0:
            QMessageBox.warning(self, "空 PDF", "该 PDF 没有页面。")
            doc.close()
            return

        if self.doc:
            self._save_current_document_state()
            self.doc.close()
        self.doc = doc
        self.file_path = os.path.abspath(path)
        self.last_file_dir = os.path.dirname(path)
        self._save_last_dir()
        doc_state = self._get_document_state(self.file_path)
        self.current_page = max(0, min(int(doc_state.get("last_page", 0)), doc.page_count - 1))
        self.zoom = float(doc_state.get("zoom", self.zoom))
        self._pending_restore_scroll = doc_state.get("scroll")
        # 加载已保存的高亮信息
        self._highlights = doc_state.get("highlights", {})
        self.bookmarks = list(doc_state.get("bookmarks", []))
        self.notes = dict(doc_state.get("notes", {}))
        self.history.clear()
        self.references.clear()
        self.search_hits = []
        self.search_index = -1
        if hasattr(self, "search_results_list"):
            self.search_results_list.clear()
        self.back_action.setEnabled(False)
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(doc.page_count)
        self.page_spin.setValue(self.current_page + 1)
        self.page_spin.blockSignals(False)
        self.page_count_label.setText(f"/ {doc.page_count}")
        self.setWindowTitle(f"PDF Reader - {os.path.basename(path)}")
        self._build_references_cache()
        self.populate_navigation_panels()
        self._remember_recent_file(self.file_path)
        self.render_all_pages()
        if self._pending_restore_scroll is not None:
            QTimer.singleShot(120, self._restore_scroll_after_render)
        self.status.showMessage(f"已打开：{path}")

    def render_all_pages(self) -> None:
        if not self.doc:
            return
        self._clear_pages()
        total_links = 0
        total_images = 0
        total = self.doc.page_count

        # 移除末尾 stretch，插入页面后再加回来。
        while self.pages_layout.count():
            item = self.pages_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for page_index in range(total):
                page = self.doc.load_page(page_index)
                matrix = fitz.Matrix(self.zoom, self.zoom)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                qpix = self._pixmap_from_fitz(pix)
                links = self._extract_links(page)
                images = self._extract_images(page)
                total_links += len(links)
                total_images += len(images)

                page_view = PageView(page_index)
                page_view.main_window = self
                page_view.set_page_content(qpix, page.rect, self.zoom, links, images)
                # 恢复该页的高亮（如果有）
                if page_index in self._highlights:
                    for rect_dict, rgba in self._highlights[page_index]:
                        try:
                            rect = fitz.Rect(**rect_dict)
                            color = QColor(*rgba)
                            page_view.user_highlights.append((rect, color))
                        except Exception:
                            continue
                frame = PageFrame(page_index, total, page_view)
                self.page_views.append(page_view)
                self.page_frames.append(frame)
                self.pages_layout.addWidget(frame, 0, Qt.AlignHCenter)

                if page_index % 10 == 0:
                    QApplication.processEvents()
        except Exception as exc:
            QMessageBox.critical(self, "渲染失败", f"页面渲染失败：\n{exc}")
        finally:
            self.pages_layout.addStretch(1)
            QApplication.restoreOverrideCursor()

        self.zoom_label.setText(f"{int(self.zoom * 100)}%")
        self.status.showMessage(
            f"第 {self.current_page + 1} / {self.doc.page_count} 页    "
            f"缩放 {int(self.zoom * 100)}%    "
            f"链接 {total_links} 个，图片 {total_images} 个"
        )
        QTimer.singleShot(0, lambda: self.scroll_to_page(self.current_page))

    def _clear_pages(self) -> None:
        for view in self.page_views:
            view.preview.hide()
        self.page_views.clear()
        self.page_frames.clear()

    def _extract_links(self, page: fitz.Page) -> List[LinkRegion]:
        regions: List[LinkRegion] = []
        for link in page.get_links():
            try:
                rect = fitz.Rect(link.get("from"))
                if rect.is_empty or rect.is_infinite:
                    continue
                kind = int(link.get("kind", 0))
                regions.append(
                    LinkRegion(
                        bbox=rect,
                        kind=kind,
                        page=link.get("page"),
                        to=link.get("to"),
                        uri=link.get("uri"),
                        raw=link,
                    )
                )
            except Exception:
                # 某些 PDF 链接元数据可能不完整，跳过即可。
                continue
        return regions

    def _extract_images(self, page: fitz.Page) -> List[ImageRegion]:
        """
        从 page.get_text('dict') 的 image block 中提取图片区域和图片内容。
        注意：这只识别 PDF 中真实嵌入的图片对象，不识别矢量图或扫描页中的局部对象。
        """
        result: List[ImageRegion] = []
        try:
            text_dict = page.get_text("dict")
        except Exception:
            return result

        for block in text_dict.get("blocks", []):
            if block.get("type") != 1:
                continue
            bbox = fitz.Rect(block.get("bbox"))
            image_bytes = block.get("image")
            if not image_bytes:
                continue
            pixmap = QPixmap()
            ok = pixmap.loadFromData(image_bytes)
            if not ok or pixmap.isNull():
                continue
            result.append(ImageRegion(bbox=bbox, pixmap=pixmap, ext=block.get("ext", "image")))
        return result

    def _pixmap_from_fitz(self, pix: fitz.Pixmap) -> QPixmap:
        if pix.alpha:
            fmt = QImage.Format_RGBA8888
        else:
            fmt = QImage.Format_RGB888
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
        return QPixmap.fromImage(img)

    def _decode_pdf_mojibake(self, text: str) -> str:
        """修复部分 PDF 命名目标中常见的 UTF-8/Latin-1 mojibake。"""
        if not text:
            return ""
        # Springer/Nature 的 nameddest 常出现 ï»¿、Â、â\x80\x93 等 mojibake。
        # 它通常是 UTF-8 字节被按 Latin-1 解码后又传给 PyMuPDF 的结果。
        suspicious = ("ï»¿", "Â", "â", "\ufeff")
        if any(token in text for token in suspicious):
            try:
                fixed = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
                if fixed.strip():
                    text = fixed
            except Exception:
                pass
        return text

    def clean_named_destination_text(self, raw_text: str) -> str:
        """把 LINK_NAMED 的 nameddest 清理成可读文本。"""
        text = self._decode_pdf_mojibake(raw_text or "")
        text = text.replace("\ufeff", "")
        text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        # 去掉类似 springernature_xxx.indd: 的源文件前缀。
        text = re.sub(r"^[^:\n\r]{0,180}:\s*", "", text)
        # 去掉末尾的内部锚点序号，例如 :68。
        text = re.sub(r"\s*:\d+\s*$", "", text)
        text = re.sub(r"\s+", " ", text).strip(" ;,|")
        return text

    def named_destination_text(self, link: LinkRegion) -> str:
        """从 LinkRegion.raw 中提取命名目标文本。"""
        raw = link.raw or {}
        value = raw.get("nameddest") or raw.get("name") or raw.get("id") or ""
        if not isinstance(value, str):
            value = str(value)
        return self.clean_named_destination_text(value)

    def infer_named_destination_title(self, preview_text: str) -> str:
        """根据命名目标文本推断右侧预览标题。"""
        # preview_text 可能已经是“链接文本...\n\n目标内容...”，先取目标内容判断。
        target = preview_text.split("目标内容：", 1)[-1]
        if "引用范围：" in preview_text or re.match(r"^\s*\d{1,4}\.\s+", target):
            return "文献引用预览"
        if re.match(r"^\s*(Fig\.?|Figure|图)\s*\d+", target, re.IGNORECASE):
            return "图引用预览"
        if re.match(r"^\s*(Table|Tab\.?|表)\s*\d+", target, re.IGNORECASE):
            return "表格引用预览"
        if re.match(r"^\s*(Sec\.?|Section|\d+(?:\.\d+)*)\s+", target, re.IGNORECASE):
            return "内部链接预览"
        return "命名目标预览"

    def render_named_destination_preview_text(self, link: LinkRegion, source_page_index: int) -> str:
        """为只有 nameddest、没有 page/to/uri 的内部链接生成预览文本。

        Nature/Springer 等 PDF 的文献引用常见形态：
            {"kind": LINK_NAMED, "page": None, "to": None, "uri": None,
             "nameddest": "springernature_xxx.indd:6. Author ...:68"}

        重要修复：Nature 风格上标引用常把范围链接拆成首尾两个超链接，
        例如 regime6–11 只有 6 和 11 两个 nameddest。这里需要从源文本
        中识别 6–11，并从参考文献缓存中补齐 7、8、9、10。
        """
        target = self.named_destination_text(link)
        if not target:
            return ""

        source = self.render_link_source_text(link, source_page_index)
        display = self.render_link_display_text(link, source_page_index)
        link_text = display or source

        # 如果目标是文献条目，先尝试把源侧的上标范围/列表完整展开。
        target_label = self._match_reference_entry_label(target)
        if target_label:
            numbers = self.extract_reference_numbers_from_link_context(link, source_page_index)
            if not numbers:
                try:
                    numbers = [int(target_label)]
                except Exception:
                    numbers = []
            expanded = self.render_reference_numbers_preview(numbers, fallback_target=target)
            if expanded:
                prefix = f"链接文本：{link_text}\n\n" if link_text else ""
                if len(numbers) > 1:
                    nums_text = ", ".join(str(n) for n in numbers)
                    return f"{prefix}引用范围：{nums_text}\n\n引用内容：\n{expanded}"
                return f"{prefix}目标内容：{expanded}"

        if link_text:
            return f"链接文本：{link_text}\n\n目标内容：{target}"
        return target

    def extract_reference_numbers_from_link_context(self, link: LinkRegion, source_page_index: int) -> List[int]:
        """从链接源文本中提取完整文献编号列表。

        适配三类常见写法：
        - Nature/Springer 上标范围：regime6–11、tasks12–14、process10,33–36
        - 方括号引用：[28, 33, 79, 103]、[4-6]
        - 括号/拆分引用：(6)、103]
        """
        source = re.sub(r"\s+", "", self.render_link_source_text(link, source_page_index) or "")
        context = re.sub(r"\s+", " ", self.render_link_context_text(link, source_page_index) or "").strip()

        # 显式 Fig./Sec./Eq./Table 不按文献处理。
        combined = f"{context} {source}".strip()
        if re.search(r"\b(fig|figure|table|tab|sec|sect|section|eq|equation)\.?\s*\d", combined, re.IGNORECASE):
            return []
        if re.search(r"图\s*\d|表\s*\d|第\s*\d+\s*(节|章)|章节|小节|公式", combined):
            return []

        # 优先解析 source，因为它通常是当前鼠标命中的引用词，如 regime6–11。
        nums = self._parse_reference_number_expression(source)
        if nums:
            return nums

        # 方括号组可能只在上下文里完整出现。
        for group in re.findall(r"\[[^\]]{1,180}\]", context):
            src_num = re.search(r"(?<!\d)(\d{1,4})(?!\d)", source)
            group_nums = self._parse_reference_number_expression(group)
            if group_nums and (not src_num or int(src_num.group(1)) in group_nums):
                return group_nums

        # 最后回退：用当前 nameddest 的编号。
        target_label = self._match_reference_entry_label(self.named_destination_text(link))
        if target_label:
            try:
                return [int(target_label)]
            except Exception:
                return []
        return []

    def _parse_reference_number_expression(self, text: str) -> List[int]:
        """解析 6–11、10,33–36、[28, 33, 79, 103] 这类编号表达式。"""
        text = (text or "").strip()
        if not text:
            return []
        text = text.replace("—", "–").replace("−", "-").replace("‑", "-").replace("‒", "-")
        # 去掉常见包裹符号，保留逗号、分号、短横线/连接号。
        text = text.strip("[](){}.;:，。；、 ")

        # 提取最像“引用编号串”的部分：至少包含一个数字，可带逗号或范围连接符。
        candidates = re.findall(
            r"(?<!\d)(\d{1,4}(?:\s*(?:[,，;；、]|[-–])\s*\d{1,4})*)(?!\d)",
            text,
        )
        if not candidates:
            return []
        # 对 regime6–11 这类词，正则会提取到最后的 6–11；对普通文本取最后一个候选更接近鼠标位置。
        expr = candidates[-1]

        result: List[int] = []
        for part in re.split(r"[,，;；、]", expr):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^(\d{1,4})\s*[-–]\s*(\d{1,4})$", part)
            if m:
                start, end = int(m.group(1)), int(m.group(2))
                if 0 < start <= end and end - start <= 80:
                    result.extend(range(start, end + 1))
                else:
                    result.extend([start, end])
                continue
            m = re.match(r"^(\d{1,4})$", part)
            if m:
                result.append(int(m.group(1)))
        # 去重并保持顺序。
        seen = set()
        ordered: List[int] = []
        for n in result:
            if n not in seen:
                ordered.append(n)
                seen.add(n)
        return ordered

    def render_reference_numbers_preview(self, numbers: List[int], fallback_target: str = "") -> str:
        """按编号列表生成文献预览文本。"""
        if not numbers:
            return fallback_target
        fallback_label = self._match_reference_entry_label(fallback_target) if fallback_target else None
        parts: List[str] = []
        missing: List[int] = []
        for n in numbers:
            key = str(n)
            entry = self.references.get(key, "")
            if not entry and fallback_label == key:
                entry = fallback_target
            if entry:
                parts.append(entry.strip())
            else:
                missing.append(n)
        if missing:
            parts.append("未能自动解析以下文献编号：" + ", ".join(str(n) for n in missing))
        return "\n\n".join(parts).strip()

    def normalize_link_target_y(self, page_index: int, page_y: Optional[float]) -> Optional[float]:
        """把 PDF 链接目标 y 坐标统一转换为 PyMuPDF 页面坐标。

        许多由 LaTeX/hyperref 生成的 PDF 内部链接目的地使用 PDF 原生坐标系
        （左下角为原点）。页面渲染、文本块和鼠标命中区域使用的是 PyMuPDF
        坐标系（左上角为原点）。如果不做转换，Fig. 4 会跑到页面底部，
        [103] 也会落到 [97] 附近。
        """
        if page_y is None or not self.doc or page_index < 0 or page_index >= self.doc.page_count:
            return page_y
        try:
            page = self.doc.load_page(page_index)
            pt = fitz.Point(0, float(page_y)) * page.transformation_matrix
            if 0 <= pt.y <= page.rect.height:
                return float(pt.y)
        except Exception:
            pass
        return page_y

    def render_page_preview(
        self,
        page_index: int,
        focus_y: Optional[float] = None,
        source_text: str = "",
        link_type: str = "internal",
    ) -> Optional[QPixmap]:
        if not self.doc or page_index < 0 or page_index >= self.doc.page_count:
            return None
        try:
            page = self.doc.load_page(page_index)
            target_width = 980.0 if not self.is_preview_panel_visible() else max(420.0, self.preview_panel.width() - 34)
            scale = min(2.4, max(1.0, target_width / max(1.0, page.rect.width)))

            clip = None
            if focus_y is not None:
                h = float(page.rect.height)
                y = max(0.0, min(float(focus_y), h))
                # 图/表通常链接到目标对象顶部，应向下多显示一些，包含图和标题。
                if link_type in {"figure", "table"}:
                    y0 = max(0.0, y - 45.0)
                    y1 = min(h, y + 390.0)
                    # 如果能在目标页找到 Fig. N / Table N 标题，按标题重新裁剪，更稳定。
                    label = self._extract_target_number_from_text(source_text)
                    caption = self._find_caption_block(page, label, link_type)
                    if caption is not None:
                        y0 = max(0.0, float(caption[1]) - 270.0)
                        y1 = min(h, float(caption[3]) + 42.0)
                    clip = fitz.Rect(0, y0, page.rect.width, y1)
                else:
                    y0 = max(0.0, y - 120.0)
                    y1 = min(h, y + 430.0)
                    clip = fitz.Rect(0, y0, page.rect.width, y1)

            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, clip=clip)
            return self._pixmap_from_fitz(pix)
        except Exception:
            return None


    def render_link_source_text(self, link: LinkRegion, page_index: int) -> str:
        if not self.doc or page_index < 0 or page_index >= self.doc.page_count:
            return ""
        try:
            page = self.doc.load_page(page_index)
            words = page.get_text("words")
            selected: List[Tuple[float, float, str]] = []
            for item in words:
                if len(item) < 5:
                    continue
                x0, y0, x1, y1, text = item[0], item[1], item[2], item[3], item[4]
                word_rect = fitz.Rect(x0, y0, x1, y1)
                if word_rect.intersects(link.bbox):
                    selected.append((y0, x0, text))
            if not selected:
                return ""
            selected.sort()
            result = " ".join(word for _, _, word in selected).strip()
            return result[:1200] + ("\n\n..." if len(result) > 1200 else "")
        except Exception:
            return ""


    def render_link_context_text(self, link: LinkRegion, page_index: int, x_margin: float = 180.0) -> str:
        """提取链接所在行的上下文，用于区分 [103] / Fig. 4 / Sec. 4.4。

        PDF 常把一个多引用拆成多个 link bbox，例如 [28, 33, 79, 103]
        中的最后一个链接区域只覆盖 "103]"；单看 bbox 内文字不足以判断类型，
        必须查看同一行附近上下文。
        """
        if not self.doc or page_index < 0 or page_index >= self.doc.page_count:
            return ""
        try:
            page = self.doc.load_page(page_index)
            center_y = (float(link.bbox.y0) + float(link.bbox.y1)) / 2.0
            tol_y = max(4.0, float(link.bbox.height) * 1.35)
            selected: List[Tuple[float, float, str]] = []
            for item in page.get_text("words"):
                if len(item) < 5:
                    continue
                x0, y0, x1, y1, text = item[0], item[1], item[2], item[3], item[4]
                wy = (float(y0) + float(y1)) / 2.0
                if abs(wy - center_y) <= tol_y and x1 >= link.bbox.x0 - x_margin and x0 <= link.bbox.x1 + x_margin:
                    selected.append((float(y0), float(x0), str(text)))
            if not selected:
                return ""
            selected.sort()
            return " ".join(word for _, _, word in selected).strip()
        except Exception:
            return ""

    def render_link_display_text(self, link: LinkRegion, page_index: int) -> str:
        source = self.render_link_source_text(link, page_index)
        context = self.render_link_context_text(link, page_index)
        text = re.sub(r"\s+", " ", context or source).strip()

        patterns = [
            r"\b(?:Fig|Figure)\.?\s*\d+(?:\.\d+)*",
            r"\b(?:Table|Tab)\.?\s*\d+(?:\.\d+)*",
            r"\b(?:Sec|Sect|Section)\.?\s*\d+(?:\.\d+)*",
            r"\b(?:Eq|Equation)\.?\s*\(?\s*\d+(?:\.\d+)*\s*\)?",
            r"图\s*\d+(?:\.\d+)*",
            r"表\s*\d+(?:\.\d+)*",
            r"公式\s*\(?\s*\d+(?:\.\d+)*\s*\)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()

        return source

    def classify_internal_link(self, link: LinkRegion, source_page_index: int) -> str:
        source = self.render_link_source_text(link, source_page_index)
        context = self.render_link_context_text(link, source_page_index)
        text = re.sub(r"\s+", " ", f"{context} {source}").strip()
        lower = text.lower()

        # 显式类型优先，避免把 Fig. 4 / Sec. 4.4 中的数字 4 当作文献 [4]。
        if re.search(r"\b(fig|figure)\.?\s*\d", lower) or re.search(r"图\s*\d", text):
            return "figure"
        if re.search(r"\b(table|tab)\.?\s*\d", lower) or re.search(r"表\s*\d", text):
            return "table"
        if re.search(r"\b(sec|sect|section)\.?\s*\d", lower) or re.search(r"第\s*\d+\s*(节|章)|章节|小节", text):
            return "section"
        if re.search(r"\b(eq|equation)\.?\s*\(?\s*\d", lower) or re.search(r"公式\s*\(?\s*\d", text):
            return "equation"

        if self._extract_reference_label(link, source_page_index):
            return "reference"
        return "internal"

    def _extract_target_number_from_text(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text or "")
        # 保留完整层级号：Sec. 4.4 应返回 4.4，而不是 4；
        # Fig. 4 / Table 2 则自然返回 4 / 2。
        match = re.search(r"(?<!\d)(\d{1,4}(?:\.\d+)*)(?!\d)", text)
        return match.group(1) if match else ""

    def _find_caption_block(self, page: fitz.Page, label: str, link_type: str) -> Optional[list]:
        if not label:
            return None
        if link_type == "figure":
            pattern = re.compile(rf"^\s*(Figure|Fig\.?|图)\s*{re.escape(label)}\b", re.IGNORECASE)
        elif link_type == "table":
            pattern = re.compile(rf"^\s*(Table|Tab\.?|表)\s*{re.escape(label)}\b", re.IGNORECASE)
        else:
            return None
        try:
            for block in page.get_text("blocks"):
                if len(block) < 5:
                    continue
                content = re.sub(r"\s+", " ", str(block[4]).strip())
                if pattern.search(content):
                    return block
        except Exception:
            return None
        return None

    def render_internal_link_target_text(
        self,
        page_index: int,
        page_y: Optional[float] = None,
        link_type: str = "internal",
        source_text: str = "",
    ) -> str:
        if not self.doc or page_index < 0 or page_index >= self.doc.page_count:
            return ""
        try:
            page = self.doc.load_page(page_index)
            blocks = [block for block in page.get_text("blocks") if len(block) >= 5 and str(block[4]).strip()]
            if not blocks:
                return ""
            blocks = sorted(blocks, key=lambda b: (round(float(b[1]), 1), round(float(b[0]), 1)))

            def clean(block: list) -> str:
                return re.sub(r"\s+", " ", str(block[4]).strip())

            target_block = None
            label = self._extract_target_number_from_text(source_text)

            if link_type == "section" and label:
                # 优先精确找目标章节标题，如 4.4 Inference Modes。
                sec_pat = re.compile(rf"^\s*{re.escape(label)}(?:\.\d+)*\s+\S|^\s*(Sec|Section)\.?\s*{re.escape(label)}", re.IGNORECASE)
                for block in blocks:
                    if sec_pat.search(clean(block)):
                        target_block = block
                        break
            elif link_type == "equation" and label:
                eq_pat = re.compile(rf"\(\s*{re.escape(label)}\s*\)")
                for block in blocks:
                    if eq_pat.search(clean(block)):
                        target_block = block
                        break

            if target_block is None and page_y is not None:
                target_block = min(
                    blocks,
                    key=lambda b: abs(float(page_y) - ((float(b[1]) + float(b[3])) / 2.0)),
                )
            if target_block is None:
                return ""

            selected = [target_block]
            idx = blocks.index(target_block)
            max_blocks = 4 if link_type in {"section", "internal"} else 2
            for next_block in blocks[idx + 1:]:
                if len(selected) >= max_blocks:
                    break
                prev = selected[-1]
                gap = float(next_block[1]) - float(prev[3])
                if gap < 32:
                    selected.append(next_block)
                else:
                    break
            entry = "\n\n".join(clean(b) for b in selected if clean(b))
            return entry[:1600] + ("\n\n..." if len(entry) > 1600 else "")
        except Exception:
            return ""

    def render_link_reference_text(
        self,
        link: LinkRegion,
        source_page_index: int,
        target_page_index: int,
        page_y: Optional[float] = None,
    ) -> str:
        # 引用编号位于“源页面”的 link.bbox 区域；文献条目位于“目标页面”。
        # 优先在目标页做严格匹配；只有目标页找不到时，才回退到参考文献区缓存。
        # 这样可以避免把正文里的“6.4”章节标题误当成编号 [6] 的文献条目。
        label = self._extract_reference_label(link, source_page_index)
        if not label:
            return ""
        norm_y = self.normalize_link_target_y(target_page_index, page_y)
        entry = self._search_reference_in_page(label, target_page_index, norm_y)
        if entry:
            return entry
        return self.references.get(label, "")

    def _match_reference_entry_label(self, content: str) -> Optional[str]:
        """判断一个文本块是否像参考文献条目开头，并返回编号。

        重点避免误判章节号：
        - 允许：[6] xxx、6. xxx、6) xxx
        - 不允许：6.4 xxx、6.4.1 xxx
        """
        text = content.strip()
        if not text:
            return None
        patterns = [
            r"^\[\s*(\d{1,4})\s*\]",       # [6] Author...
            r"^(\d{1,4})\.\s+(?=\S)",      # 6. Author...，要求点号后有空白
            r"^(\d{1,4})\)\s+(?=\S)",      # 6) Author...
        ]
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                return match.group(1)
        return None

    def _find_reference_section_start(self, all_blocks: List[Tuple[int, list]]) -> int:
        """返回参考文献区开始的 block 下标；找不到则返回 -1。

        不再从全文扫描“6.”这类编号，因为正文中的 6.4、7.1 等章节号
        很容易被误当作参考文献编号。
        """
        heading_re = re.compile(
            r"^(references|bibliography|works\s+cited|literature\s+cited|参考文献|参考资料)\b",
            re.IGNORECASE,
        )
        for idx, (_, block) in enumerate(all_blocks):
            content = str(block[4]).strip()
            normalized = re.sub(r"\s+", " ", content)
            # 参考文献标题通常很短；过长文本即使含 references，也不当作章节标题。
            if len(normalized) <= 80 and heading_re.search(normalized):
                return idx + 1
        return -1

    def _search_reference_in_page(self, label: str, page_index: int, page_y: Optional[float] = None) -> str:
        if not self.doc or page_index < 0 or page_index >= self.doc.page_count:
            return ""
        try:
            page = self.doc.load_page(page_index)
            blocks = [block for block in page.get_text("blocks") if len(block) >= 5]
            blocks = sorted(blocks, key=lambda item: (round(item[1], 1), round(item[0], 1)))

            def entry_from_block(block) -> str:
                content = str(block[4]).strip()
                # 一个 block 内可能包含多个参考文献条目，例如 IEEE 双栏参考文献区：
                # "... [41] xxx ... [42] xxx ..."
                for entry_label, entry in self._split_reference_entries_from_text(content):
                    if entry_label == label:
                        return entry
                if self._match_reference_entry_label(content) == label:
                    return re.sub(r"\s+", " ", content)[:1800]
                return ""

            # 如果 PDF 链接给出了目标 y 坐标，先在该位置附近找；
            # 但不要要求整个 block 以 [41] 开头，因为双栏 PDF 常把多条参考文献合成一个 block。
            if page_y is not None:
                near_blocks = sorted(
                    blocks,
                    key=lambda b: abs(float(page_y) - ((float(b[1]) + float(b[3])) / 2.0)),
                )[:10]
                for block in near_blocks:
                    entry = entry_from_block(block)
                    if entry:
                        return entry

            # 全页兜底查找。
            for block in blocks:
                entry = entry_from_block(block)
                if entry:
                    return entry

            return ""
        except Exception:
            return ""

    def _extract_reference_label(self, link: LinkRegion, page_index: int) -> str:
        source_text = self.render_link_source_text(link, page_index)
        context_text = self.render_link_context_text(link, page_index)
        source = re.sub(r"\s+", " ", source_text or "").strip()
        context = re.sub(r"\s+", " ", context_text or "").strip()

        if not source and not context:
            return ""

        # 如果同一行出现 Fig./Sec./Eq./Table 等显式前缀，不能把里面的数字当作文献。
        combined = f"{context} {source}".strip()
        lower = combined.lower()
        if re.search(r"\b(fig|figure|table|tab|sec|sect|section|eq|equation)\.?\s*\d", lower):
            return ""
        if re.search(r"图\s*\d|表\s*\d|第\s*\d+\s*(节|章)|章节|小节|公式", combined):
            return ""

        # 完整引用：[103]、[28, 33, 79, 103]
        for text in (source, context):
            match = re.search(r"\[\s*(\d{1,4})(?=\s*(?:[,，;；、\-–—\]\)]|$))", text)
            if match:
                # 如果 source 本身是局部编号 103]，优先返回 source 中的数字。
                src_num = re.search(r"(?<!\d)(\d{1,4})(?!\d)", source)
                if src_num and src_num.group(1) in re.findall(r"\d{1,4}", match.group(0) + text[text.find(match.group(0)):text.find(match.group(0))+80]):
                    return src_num.group(1)
                return match.group(1)

        # PyMuPDF 常把多引用拆成多个 link bbox，例如 source 只有 "[28,"、"33,"、"103]"。
        src_num = re.search(r"(?<!\d)(\d{1,4})(?!\d)", source)
        if src_num:
            num = src_num.group(1)
            # 只有当上下文里存在包含该数字的方括号引用组时，才认作文献引用。
            for group in re.findall(r"\[[^\]]{1,160}\]", context):
                if num in re.findall(r"\d{1,4}", group):
                    return num
            # 或者 source 自身带有 [ 或 ] 或逗号/分号，说明它很可能是被拆开的引用片段。
            if re.search(r"[\[\],，;；、\]]", source):
                return num

        # 少量文档用 (6) 作为文献引用；这里只允许近乎独立的括号编号。
        match = re.match(r"^\(\s*(\d{1,4})(?=\s*(?:[,，;；、\-–—\)]|$))", source)
        if match:
            return match.group(1)

        return ""

    def _split_reference_entries_from_text(self, content: str) -> List[Tuple[str, str]]:
        """从一个文本块中拆出多个参考文献条目。

        兼容两类常见参考文献格式：
        - Nature/Springer: 1. Author ...
        - IEEE/arXiv: [1] Author ...

        重点修复：很多双栏 PDF 会把一整列参考文献抽成一个 text block，
        甚至 block 开头可能是上一条参考文献的尾巴，例如
        "... IEEE, 2022. [41] Shuran Song ... [42] ..."
        因此不能只判断 block 开头，也不能只按 "1." 这种格式拆分。
        """
        text = self._decode_pdf_mojibake(content or "").replace("\ufeff", "")
        if not text.strip():
            return []

        # 优先处理方括号参考文献：[1] ... [2] ...
        # 注意：这里只在参考文献区调用，不在正文全文扫描，所以不会把正文引用 [41,50] 当条目。
        matches = list(re.finditer(r"(?<!\w)\[\s*(\d{1,4})\s*\]\s+", text))

        # Nature/Springer 常用：1. Author ... 2. Author ...
        # 先按行首找；如果 PDF 抽取丢失换行，再用“编号. + 大写作者/左括号”兜底。
        if not matches:
            matches = list(re.finditer(r"(?m)^\s*(\d{1,4})\.\s+", text))
        if len(matches) <= 1:
            dot_matches = list(re.finditer(r"(?<!\d)(\d{1,4})\.\s+(?=[A-Z\[\u00c0-\u024F])", text))
            if len(dot_matches) > len(matches):
                matches = dot_matches

        if not matches:
            return []

        entries: List[Tuple[str, str]] = []
        for i, match in enumerate(matches):
            label = match.group(1)
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            entry = text[start:end].strip()
            entry = re.sub(r"\s+", " ", entry)
            # 过滤掉短噪声；正常文献条目远大于 20 字符。
            if len(entry) >= 20:
                entries.append((label, entry[:1800] + ("\n\n..." if len(entry) > 1800 else "")))
        return entries

    def _cache_reference_entries_from_text(self, content: str) -> int:
        count = 0
        for label, entry in self._split_reference_entries_from_text(content):
            if label not in self.references:
                self.references[label] = entry
                count += 1
        return count

    def _cache_named_destination_references(self) -> int:
        """从 LINK_NAMED 的 nameddest 中缓存可直接获得的文献条目。"""
        if not self.doc:
            return 0
        count = 0
        try:
            for page_index in range(self.doc.page_count):
                page = self.doc.load_page(page_index)
                for raw_link in page.get_links():
                    raw = raw_link or {}
                    value = raw.get("nameddest") or raw.get("name") or raw.get("id") or ""
                    if not value:
                        continue
                    text = self.clean_named_destination_text(str(value))
                    label = self._match_reference_entry_label(text)
                    if label and label not in self.references:
                        self.references[label] = text[:1800] + ("\n\n..." if len(text) > 1800 else "")
                        count += 1
        except Exception:
            pass
        return count

    def _find_sequential_reference_start(self, all_blocks: List[Tuple[int, list]]) -> int:
        """无 References 标题时，查找从 1.、2.、3. 连续开始的参考文献区。"""
        for idx, (_, block) in enumerate(all_blocks):
            content = str(block[4]).strip()
            entries = self._split_reference_entries_from_text(content)
            labels = [label for label, _ in entries[:3]]
            if labels[:2] == ["1", "2"] or labels[:3] == ["1", "2", "3"]:
                return idx
            first = self._match_reference_entry_label(content)
            if first == "1" and idx + 1 < len(all_blocks):
                next_content = str(all_blocks[idx + 1][1][4]).strip()
                if self._match_reference_entry_label(next_content) == "2":
                    return idx
        return -1

    def _is_reference_section_end(self, content: str) -> bool:
        """判断是否已经离开参考文献区，避免把 Appendix 正文里的 [1] 当参考文献。"""
        text = re.sub(r"\s+", " ", content or "").strip()
        if not text:
            return False
        if len(text) <= 120 and re.match(
            r"^(appendix|appendices|supplementary|supplemental|附录)\b",
            text,
            re.IGNORECASE,
        ):
            return True
        return False

    def _build_references_cache(self) -> None:
        if not self.doc:
            return
        try:
            all_blocks: List[Tuple[int, list]] = []
            for page_index in range(self.doc.page_count):
                page = self.doc.load_page(page_index)
                for block in page.get_text("blocks"):
                    if len(block) >= 5:
                        all_blocks.append((page_index, block))
            all_blocks.sort(key=lambda item: (item[0], round(item[1][1], 1), round(item[1][0], 1)))

            # 先把 named destination 自带的文献条目缓存起来。
            self._cache_named_destination_references()

            start_idx = self._find_reference_section_start(all_blocks)
            if start_idx < 0:
                # Nature 等期刊 PDF 可能没有显式 References 标题，正文后直接从 1. 开始列文献。
                start_idx = self._find_sequential_reference_start(all_blocks)
            if start_idx < 0:
                # 找不到可靠的参考文献区时，不做全文宽松扫描，避免把正文“6.4”误收为 [6]。
                return

            scan_blocks = all_blocks[start_idx:]
            for idx, (page_idx, block) in enumerate(scan_blocks):
                content = str(block[4]).strip()
                if self._is_reference_section_end(content):
                    break
                # 一个 block 内可能包含多个条目，如 Nature PDF 的 1–8，或 IEEE/arXiv 的 [1]–[54]。
                if self._cache_reference_entries_from_text(content) > 0:
                    continue

                matched_label = self._match_reference_entry_label(content)
                if not matched_label:
                    continue

                selected = [block]
                for next_idx in range(idx + 1, len(scan_blocks)):
                    next_page_idx, next_block = scan_blocks[next_idx]
                    if next_page_idx != page_idx:
                        break
                    next_content = str(next_block[4]).strip()
                    if self._match_reference_entry_label(next_content):
                        break
                    prev = selected[-1]
                    gap = next_block[1] - prev[3]
                    if gap < 26:
                        selected.append(next_block)
                    else:
                        break
                entry = "\n\n".join(
                    str(b[4]).strip() for b in selected if str(b[4]).strip()
                )
                if matched_label not in self.references:
                    self.references[matched_label] = entry[:1800] + (
                        "\n\n..." if len(entry) > 1800 else ""
                    )
        except Exception:
            pass

    def activate_link(self, link: LinkRegion) -> None:
        if not self.doc:
            return
        if link.uri:
            webbrowser.open(link.uri)
            self.status.showMessage(f"已打开外部链接：{link.uri}")
            return
        if link.page is not None and 0 <= int(link.page) < self.doc.page_count:
            self.history.append((self.current_page, self.scroll_area.verticalScrollBar().value()))
            self.back_action.setEnabled(True)
            target_page = int(link.page)
            self.current_page = target_page
            self.scroll_to_page(target_page, self.normalize_link_target_y(target_page, link.to.y if link.to else None))
            self._sync_page_spin(target_page)
            return
        self.status.showMessage("该链接类型暂未实现或 PDF 没有提供可跳转目标。")

    def go_back(self) -> None:
        if not self.doc or not self.history:
            return
        page_index, scroll_value = self.history.pop()
        self.current_page = page_index
        self.back_action.setEnabled(bool(self.history))
        self._sync_page_spin(page_index)
        self.scroll_area.verticalScrollBar().setValue(scroll_value)

    def prev_page(self) -> None:
        if self.doc and self.current_page > 0:
            self.scroll_to_page(self.current_page - 1)

    def next_page(self) -> None:
        if self.doc and self.current_page + 1 < self.doc.page_count:
            self.scroll_to_page(self.current_page + 1)

    def on_page_spin_changed(self, value: int) -> None:
        if self.doc and not self._syncing_page_spin:
            self.scroll_to_page(max(0, min(value - 1, self.doc.page_count - 1)))

    def quick_jump_page(self) -> None:
        if not self.doc:
            return
        text = self.quick_page_edit.text().strip()
        if not text.isdigit():
            self.status.showMessage("请输入有效页码。")
            return
        page_no = int(text)
        if not 1 <= page_no <= self.doc.page_count:
            self.status.showMessage(f"页码范围应为 1 - {self.doc.page_count}。")
            return
        self.scroll_to_page(page_no - 1)
        self.quick_page_edit.clear()

    def change_zoom(self, factor: float) -> None:
        if not self.doc:
            return
        keep_page = self.current_page
        self.zoom = max(0.25, min(5.0, self.zoom * factor))
        self.current_page = keep_page
        self.render_all_pages()

    def fit_width(self) -> None:
        if not self.doc:
            return
        page = self.doc.load_page(self.current_page)
        viewport_width = max(320, self.scroll_area.viewport().width() - 76)
        self.zoom = max(0.25, min(5.0, viewport_width / page.rect.width))
        self.render_all_pages()

    def scroll_to_page(self, page_index: int, page_y: Optional[float] = None) -> None:
        if not self.doc or not self.page_frames:
            return
        page_index = max(0, min(page_index, len(self.page_frames) - 1))
        frame = self.page_frames[page_index]
        y = frame.y()
        if page_y is not None:
            # frame 内部：页码标题 + 间距后才是实际页面。
            y += int(page_y * self.zoom) + 24
        self._syncing_scroll = True
        self.scroll_area.verticalScrollBar().setValue(max(0, y - 12))
        self._syncing_scroll = False
        self.current_page = page_index
        self._sync_page_spin(page_index)
        self._update_status_current_page()
        self.update_note_editor_for_page(page_index)

    def on_scroll_changed(self, value: int) -> None:
        if self._syncing_scroll or not self.doc or not self.page_frames:
            return
        viewport_mid = value + self.scroll_area.viewport().height() // 2
        current = self.current_page
        for frame in self.page_frames:
            top = frame.y()
            bottom = top + frame.height()
            if top <= viewport_mid <= bottom:
                current = frame.page_index
                break
            if viewport_mid < top:
                current = frame.page_index
                break
        if current != self.current_page:
            self.current_page = current
            self._sync_page_spin(current)
            self._update_status_current_page()
            self.update_note_editor_for_page(current)

    def _sync_page_spin(self, page_index: int) -> None:
        self._syncing_page_spin = True
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(page_index + 1)
        self.page_spin.blockSignals(False)
        self._syncing_page_spin = False

    def _update_status_current_page(self) -> None:
        if not self.doc:
            return
        self.status.showMessage(
            f"第 {self.current_page + 1} / {self.doc.page_count} 页    缩放 {int(self.zoom * 100)}%"
        )

    def toggle_preview_panel(self) -> None:
        visible = self.preview_panel_action.isChecked()
        self.preview_panel.setVisible(visible)
        if visible:
            self.preview_panel.clear_preview()
            self.status.showMessage("预览栏已显示", 2000)
        else:
            self.status.showMessage("预览栏已隐藏", 2000)

    def is_preview_panel_visible(self) -> bool:
        return self.preview_panel.isVisible()

    def show_preview_text(self, title: str, text: str) -> None:
        self.preview_panel.show_text(title, text)

    def show_preview_image(self, title: str, pixmap: QPixmap) -> None:
        self.preview_panel.show_image(title, pixmap)

    def clear_preview_if_needed(self) -> None:
        # 保持右侧预览稍微稳定，不在鼠标离开瞬间清空；浮窗模式则立即隐藏。
        if not self.is_preview_panel_visible():
            return

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith('.pdf'):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if path.lower().endswith('.pdf'):
                    self.open_pdf(path)
                    event.acceptProposedAction()
                    return
        event.ignore()


    def _document_key(self, path: Optional[str] = None) -> str:
        return os.path.abspath(path or self.file_path or "")

    def _load_app_state(self) -> dict:
        try:
            if self.state_file.exists():
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        data.setdefault("documents", {})
                        data.setdefault("recent_files", [])
                        return data
        except Exception:
            pass
        return {"documents": {}, "recent_files": []}

    def _save_app_state(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.app_state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _get_document_state(self, path: str) -> dict:
        key = self._document_key(path)
        docs = self.app_state.setdefault("documents", {})
        state = docs.get(key, {})
        return state if isinstance(state, dict) else {}

    def _save_current_document_state(self) -> None:
        if not self.file_path or not self.doc:
            return
        if hasattr(self, "note_editor") and self.note_editor_page is not None:
            # 自动保存当前页笔记草稿。
            text = self.note_editor.toPlainText().strip()
            key = str(self.note_editor_page)
            if text:
                self.notes[key] = text
            else:
                self.notes.pop(key, None)
        docs = self.app_state.setdefault("documents", {})
        docs[self._document_key()] = {
            "last_page": int(self.current_page),
            "scroll": int(self.scroll_area.verticalScrollBar().value()) if hasattr(self, "scroll_area") else 0,
            "zoom": float(self.zoom),
            "bookmarks": self.bookmarks,
            "notes": self.notes,
            "highlights": self._highlights,
        }
        self._save_app_state()

    def save_highlights(self) -> None:
        """手动触发保存当前文档状态（包括高亮）。"""
        self._save_current_document_state()
        self.status.showMessage("已保存高亮和其他修改", 2000)

    def record_highlight(self, page_index: int, rect: fitz.Rect, color: QColor) -> None:
        """记录用户在指定页面的高亮信息，以便保存到状态文件。"""
        # 将 fitz.Rect 转为可序列化的 dict
        rect_dict = {
            "x0": rect.x0,
            "y0": rect.y0,
            "x1": rect.x1,
            "y1": rect.y1,
        }
        rgba = (color.red(), color.green(), color.blue(), color.alpha())
        self._highlights.setdefault(page_index, []).append((rect_dict, rgba))

    def _remember_recent_file(self, path: str) -> None:
        path = self._document_key(path)
        recent = [p for p in self.app_state.get("recent_files", []) if p != path and os.path.exists(p)]
        recent.insert(0, path)
        self.app_state["recent_files"] = recent[:20]
        self._save_app_state()

    def _restore_scroll_after_render(self) -> None:
        if self._pending_restore_scroll is None:
            return
        try:
            self.scroll_area.verticalScrollBar().setValue(int(self._pending_restore_scroll))
        except Exception:
            pass
        self._pending_restore_scroll = None

    def _load_last_dir(self) -> str:
        try:
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    last_dir = config.get("last_file_dir", "")
                    if last_dir and os.path.isdir(last_dir):
                        return last_dir
        except Exception:
            pass
        return ""

    def _save_last_dir(self) -> None:
        try:
            config = {"last_file_dir": self.last_file_dir}
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._save_current_document_state()
        self._save_last_dir()
        for view in self.page_views:
            view.preview.hide()
        if self.doc:
            self.doc.close()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Reader")
    app.setOrganizationName("LocalTools")

    win = PdfReaderWindow()
    win.show()

    if len(sys.argv) > 1:
        candidate = sys.argv[1]
        if os.path.exists(candidate):
            win.open_pdf(candidate)
        else:
            QMessageBox.warning(win, "文件不存在", f"找不到文件：\n{candidate}")

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
