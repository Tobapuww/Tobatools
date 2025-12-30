from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt

DISCLAIMER_TEXT = (
    "拖把工具箱免责声明\n\n"
    "1. 本声明仅适用于一加Ace Pro（机型代号PGP110），刷机前需确认设备型号、系统版本与所选刷机包完全匹配，非该机型或操作不当导致的任何问题，本人/本平台不承担责任。\n\n"
    "2. 刷机过程中严禁中途拔线、强制关机或中断操作，需使用优质数据线保持稳定连接，同时确保手机电量≥50%，否则可能导致设备变砖、系统崩溃等不可逆损坏，相关风险及损失由操作者自行承担。\n\n"
    "3. 操作者需提前校验兼容性：确认设备BL锁状态、OEM解锁设置、已装软件等与刷机包无冲突，若因兼容性问题引发设备故障，本人/本平台不承担责任。\n\n"
    "4. 数据备份提示：具备丰富刷机经验的专业用户可自主判断是否备份；新手/小白用户必须提前备份重要数据（照片、联系人、文件等），且解锁BL锁会自动清空所有数据，刷机相关的数据丢失风险由操作者自行承担。\n\n"
    "5. 因刷机环境差异，本工具并不适配所有电脑系统，可能会出现不兼容的情况，本人/本平台仅提供刷机相关教程或参考信息，不保证刷机结果，操作者需自行承担刷机带来的全部风险（包括但不限于设备损坏、功能异常等）。"
)


class DisclaimerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("免责声明")
        self.setModal(True)
        self.resize(680, 460)

        layout = QVBoxLayout(self)
        title = QLabel("请仔细阅读以下免责声明：")
        title.setProperty("heading", True)
        layout.addWidget(title)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(DISCLAIMER_TEXT)
        layout.addWidget(text, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_disagree = QPushButton("不同意并退出")
        self.btn_agree = QPushButton("同意并继续")
        btn_row.addWidget(self.btn_disagree)
        btn_row.addWidget(self.btn_agree)
        layout.addLayout(btn_row)

        self.btn_disagree.clicked.connect(self.reject)
        self.btn_agree.clicked.connect(self.accept)
