from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt
from qfluentwidgets import MessageBox

ABOUT_TEXT = (
    "拖把工具箱0.3.0公开版\n\n"
    "感谢以下贡献者与支持：\n\n"
    "• 移植包开发者&工具箱刷机逻辑：@秋詞、@Lucky\n"
    "• 刷机工具开发者：@Tobapuw、@人美心善且温柔\n"
    "• 官改下载存储服务：@可泺'KoCleo\n"
    "• 官方包链接提供：@by 北辞（北梦之境）\n"
    "• 工具箱依赖支持：@酸奶  -O神开发者 \n"
    "• 工具箱UI框架支持：@zhiyiYo PyQt-Fluent-Widgets \n"
    "该框架遵循 GNU General Public License v3.0（GPLv3）协议，其相关权利归属原作者所有，开源组件的源代码可通过其官方仓库获取\n\n"
    "注意：本工具下载页的移植包固件下载已获得作者@秋詞和@Lucky的正式授权，任何人未经授权不得二次分发。\n"
    "2025 ©️ Tobapuw 版权所有。未经授权，不得复制、修改、分发、传播本软件的任何部分（包括源代码、界面设计、文档等）。\n\n"
    "工具开发技术栈：Python\n"
)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent = parent

    def exec(self):
        box = MessageBox("关于", ABOUT_TEXT, self._parent or self)
        try:
            box.setClosableOnMaskClicked(True)
            box.setDraggable(True)
        except Exception:
            pass
        return box.exec()
