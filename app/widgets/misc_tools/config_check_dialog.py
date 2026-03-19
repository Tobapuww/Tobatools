import os
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from app.components.log_widget import LogWidget

class _ConfigCheckDialog(QDialog):
    def __init__(self, config_path: str, errors: list, warnings: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置文件检测结果")
        self.resize(800, 600)

        layout = QVBoxLayout(self)

        info_label = QLabel(f"文件: {os.path.basename(config_path)}")
        info_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(info_label)

        summary = QLabel(f"错误: {len(errors)} 个  |  警告: {len(warnings)} 个")
        if errors:
            summary.setStyleSheet("color: #ff4d4f; font-size: 13px;")
        elif warnings:
            summary.setStyleSheet("color: #faad14; font-size: 13px;")
        else:
            summary.setText("✅ 没有发现问题")
            summary.setStyleSheet("color: #52c41a; font-size: 13px; font-weight: bold;")
        layout.addWidget(summary)

        result_text = LogWidget()
        layout.addWidget(result_text)

        content = []

        if errors:
            content.append("\n=== 错误 (Errors) ===")
            for err in errors:
                content.append(f"\n❌ 行 {err['line']}, 列 {err['col']}: {err['type']}")
                content.append(f"   {err['msg']}")
                if 'suggestion' in err:
                    content.append(f"   建议: {err['suggestion']}")

        if warnings:
            content.append("\n\n=== 警告 (Warnings) ===")
            for warn in warnings:
                content.append(f"\n⚠️  行 {warn['line']}, 列 {warn['col']}: {warn['type']}")
                content.append(f"   {warn['msg']}")
                if 'suggestion' in warn:
                    content.append(f"   建议: {warn['suggestion']}")

        if not errors and not warnings:
            content.append("\n✅ 配置文件语法正确，没有发现问题！")
            content.append("\n可以安全使用此配置文件进行刷机。")

        result_text.setPlainText('\n'.join(content))
        layout.addWidget(result_text)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
