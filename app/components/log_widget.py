from PySide6.QtWidgets import QTextBrowser
from PySide6.QtGui import QFont, QTextCursor, QColor, QTextCharFormat
from PySide6.QtCore import Qt

class LogWidget(QTextBrowser):
    """
    精美的日志组件，支持普通日志输出、步骤化日志追加与状态更新（如 ... OK / Error）。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._step_blocks = {}
        self._step_counter = 0
        self._init_ui()

    def _init_ui(self):
        font = QFont("Cascadia Code")
        font.setStyleHint(QFont.Monospace)
        # 尝试使用多种常见等宽字体作为回退，包含 Windows/Mac/Linux 常见编程字体
        font.setFamilies([
            "Cascadia Code", 
            "Segoe UI Mono", 
            "JetBrains Mono", 
            "Source Code Pro", 
            "Consolas", 
            "Fira Code", 
            "Roboto Mono", 
            "Menlo", 
            "Monaco", 
            "Courier New", 
            "monospace"
        ])
        font.setPointSize(9)
        self.setFont(font)
        
        self.setStyleSheet("""
            QTextBrowser {
                background-color: #ffffff;
                color: #1f2329;
                border: 1px solid #d9d9d9;
                border-radius: 8px;
                padding: 10px;
                selection-background-color: #cce7ff;
                selection-color: #1f2329;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 12px;
                margin: 6px 2px 6px 0;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 0, 0, 0.22);
                min-height: 36px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(0, 0, 0, 0.34);
            }
            QScrollBar::handle:vertical:pressed {
                background: rgba(42, 116, 218, 0.55);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                border: none;
                background: transparent;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
            QScrollBar:horizontal {
                background: transparent;
                height: 12px;
                margin: 0 6px 2px 6px;
                border: none;
            }
            QScrollBar::handle:horizontal {
                background: rgba(0, 0, 0, 0.22);
                min-width: 36px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal:hover {
                background: rgba(0, 0, 0, 0.34);
            }
            QScrollBar::handle:horizontal:pressed {
                background: rgba(42, 116, 218, 0.55);
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                border: none;
                background: transparent;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent;
            }
        """)
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextBrowser.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def clear_log(self):
        self.clear()
        self._step_blocks.clear()
        self._step_counter = 0

    def append_log(self, text: str, color: str = "#1f2329", bold: bool = False):
        """
        普通的日志追加。
        """
        self.moveCursor(QTextCursor.End)
        cursor = self.textCursor()
        if not cursor.atBlockStart():
            cursor.insertText("\n")
            
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Bold)
            
        cursor.insertText(text, fmt)
        cursor.insertText("\n")
        self.ensureCursorVisible()

    def start_step(self, step_id: str, text: str):
        """
        开始一个步骤，输出类似 "重启至bootloader..."，并返回该步骤的 ID 以供后续更新状态。
        """
        self.moveCursor(QTextCursor.End)
        cursor = self.textCursor()
        
        if not cursor.atBlockStart():
            cursor.insertText("\n")
            
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#1677ff"))
        
        step_text = f"{text}... "
        cursor.insertText(step_text, fmt)
        
        block_num = cursor.blockNumber()
        self._step_blocks[step_id] = block_num
        
        cursor.insertText("\n")
        self.ensureCursorVisible()

    def finish_step(self, step_id: str, success: bool, detail: str = ""):
        """
        完成一个步骤，在对应的行末尾追加 "OK" 或 "Error"。
        """
        if step_id not in self._step_blocks:
            return
            
        block_num = self._step_blocks[step_id]
        block = self.document().findBlockByNumber(block_num)
        if not block.isValid():
            return
            
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.EndOfBlock)
        
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold)
        if success:
            fmt.setForeground(QColor("#00b42a")) # 绿色 OK
            status_text = "OK"
        else:
            fmt.setForeground(QColor("#f53f3f")) # 红色 Error
            status_text = "Error"
            
        cursor.insertText(status_text, fmt)
        
        if detail:
            fmt.setForeground(QColor("#f53f3f") if not success else QColor("#4e5969"))
            fmt.setFontWeight(QFont.Normal)
            cursor.insertText(f" ({detail})", fmt)
            
        # 恢复光标到末尾并滚动
        self.moveCursor(QTextCursor.End)
        self.ensureCursorVisible()
