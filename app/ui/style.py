"""深色主题样式表（LiveDub 2.0 视觉）。"""
from __future__ import annotations

import pathlib

_ASSETS = (pathlib.Path(__file__).parent / "assets").as_posix()
ASSETS_DIR = pathlib.Path(__file__).parent / "assets"
ICON_PATH = ASSETS_DIR / "icon.png"
ARROW_DOWN = f"{_ASSETS}/chevron-down.svg"
ARROW_UP = f"{_ASSETS}/chevron-up.svg"
CHECK = f"{_ASSETS}/check.svg"

# 设计令牌
BG = "#0b0d12"
PANEL = "#12151d"
PANEL2 = "#171b25"
BORDER = "#212734"
BORDER2 = "#2f3749"
TEXT = "#e9edf6"
MUTED = "#8b95ab"
ACCENT = "#4b7cf3"
ACCENT2 = "#7a5cff"

DARK_QSS = f"""
/* ---------- 基础 ---------- */
QWidget {{
    background: {BG}; color: {TEXT};
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC";
    font-size: 13px;
    outline: none;
}}
QMainWindow, QDialog {{
    background: qlineargradient(x1:0, y1:0, x2:0.7, y2:1,
                stop:0 #0d1017, stop:0.55 #0b0d12, stop:1 #090a0f);
}}
QWidget#central {{ background: transparent; }}
QLabel {{ background: transparent; }}
QToolTip {{
    background: {PANEL2}; color: {TEXT}; border: 1px solid {BORDER2};
    border-radius: 6px; padding: 5px 8px;
}}

/* ---------- 顶部 ---------- */
QLabel#logo {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {ACCENT}, stop:1 {ACCENT2});
    border-radius: 11px; color: #ffffff; font-size: 16px; font-weight: 800;
}}
QLabel#h1 {{ font-size: 20px; font-weight: 700; color: #ffffff; }}
QLabel#sub {{ color: {MUTED}; font-size: 12px; }}

QFrame#pill {{
    background: {PANEL2}; border: 1px solid {BORDER};
    border-radius: 13px;
}}
QLabel#pill_txt {{ color: {MUTED}; font-size: 12px; }}

/* ---------- 卡片（QGroupBox） ---------- */
QGroupBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 14px;
    margin-top: 14px;
    padding: 13px 14px 8px 14px;
    font-size: 13px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    top: 2px;
    padding: 0 4px;
    background: transparent;
    color: {MUTED};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
}}

QFrame#card {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 14px;
}}
QFrame#hline {{ background: {BORDER}; max-height: 1px; border: none; }}

/* ---------- 选项卡 ---------- */
QTabWidget::pane {{ border: none; background: transparent; top: -1px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {MUTED};
    padding: 8px 20px; margin-right: 6px;
    border: none; border-radius: 9px;
    font-size: 13px; font-weight: 600;
}}
QTabBar::tab:hover {{ color: #cdd6e6; background: #161a23; }}
QTabBar::tab:selected {{
    color: #ffffff;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 rgba(75,124,243,0.22), stop:1 rgba(122,92,255,0.18));
    border: 1px solid rgba(96,132,255,0.35);
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {PANEL2};
    border: 1px solid {BORDER2};
    border-radius: 9px;
    padding: 7px 15px;
    color: #dbe2f0;
    font-weight: 500;
}}
QPushButton:hover {{ background: #1e2431; border-color: #3b465d; color: #ffffff; }}
QPushButton:pressed {{ background: #151922; }}
QPushButton:disabled {{ color: #4e5567; background: #12151b; border-color: #1c212c; }}

QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {ACCENT}, stop:1 {ACCENT2});
    border: none; color: #ffffff;
    font-weight: 700; font-size: 14px;
    padding: 10px 26px; border-radius: 10px;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #5b8bff, stop:1 #8b6dff);
}}
QPushButton#primary:pressed {{ background: #3f68d6; }}
QPushButton#primary[running="true"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #e0524f, stop:1 #b3374a);
}}
QPushButton#primary[running="true"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #f0605d, stop:1 #c84558);
}}
QPushButton#ghost {{
    background: transparent; border: 1px solid {BORDER2}; color: {MUTED};
    padding: 7px 12px;
}}
QPushButton#ghost:hover {{ color: #ffffff; border-color: #46527a; }}
QPushButton#swap {{
    background: {PANEL2}; border: 1px solid {BORDER2}; border-radius: 17px;
    padding: 0; font-size: 16px; color: {MUTED};
}}
QPushButton#swap:hover {{ color: #ffffff; border-color: {ACCENT}; }}

/* ---------- 输入控件 ---------- */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: #0f121a;
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 5px 10px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    min-height: 16px;
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: #35405a; background: #11141d;
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT}; background: #101420;
}}
QComboBox:editable {{ padding-right: 4px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({ARROW_DOWN}); width: 14px; height: 14px; }}
QComboBox::down-arrow:on {{ image: url({ARROW_UP}); }}
QComboBox QAbstractItemView {{
    background: {PANEL2}; border: 1px solid {BORDER2}; border-radius: 9px;
    selection-background-color: {ACCENT}; selection-color: #ffffff;
    padding: 5px; outline: none;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: transparent; border: none; width: 20px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({ARROW_UP}); width: 12px; height: 12px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({ARROW_DOWN}); width: 12px; height: 12px;
}}

/* ---------- 复选框 ---------- */
QCheckBox {{ spacing: 9px; color: #d3dae8; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid #39435c; background: #0f121a;
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {ACCENT}, stop:1 {ACCENT2});
    border-color: transparent;
    image: url({CHECK});
}}

/* ---------- 列表 / 历史 ---------- */
QListWidget {{ background: transparent; border: none; outline: none; padding: 0; }}
QListWidget::item {{ border: none; margin: 0; padding: 0; }}
QListWidget::item:selected {{ background: transparent; }}

QFrame#hist {{
    background: #0f1219; border: 1px solid {BORDER}; border-radius: 11px;
}}
QFrame#hist[dir="in"] {{ border-left: 3px solid #38d39f; }}
QFrame#hist[dir="out"] {{ border-left: 3px solid #5b8bff; }}
QLabel#hist_src {{ color: {MUTED}; font-size: 12px; }}
QLabel#hist_tgt {{ color: #eef2fa; font-size: 14px; font-weight: 600; }}
QLabel#hist_time {{ color: #5f6981; font-size: 10px; font-family: Consolas; }}

/* ---------- 文字 ---------- */
QLabel#field_cap {{ color: {MUTED}; font-size: 11px; font-weight: 600; }}
QLabel#live_src {{ color: #a8b3c9; font-size: 14px; }}
QLabel#live_tgt {{ color: #ffffff; font-size: 22px; font-weight: 700; }}
QLabel#chip {{
    color: #93a0ba; font-size: 11px; font-family: Consolas;
    background: #0f1219; border: 1px solid {BORDER};
    border-radius: 8px; padding: 3px 9px;
}}
QLabel#chip[hot="true"] {{ color: #8ee0b6; border-color: #1f4a3b; }}
QLabel#stat {{ color: #7b8499; font-size: 11px; font-family: Consolas; }}
QLabel#warn {{ color: #f0b350; font-size: 12px; }}
QLabel#ok {{ color: #4ade80; font-size: 12px; }}
QLabel#help {{ color: #b9c3d6; font-size: 13px; line-height: 170%; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 2px 2px 0; }}
QScrollBar::handle:vertical {{
    background: #2c3446; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: #3c475f; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
"""


OVERLAY_QSS = f"""
QFrame#card {{
    background: rgba(14,17,24, {int(255 * 0.90)});
    border: 1px solid rgba(120,150,255, 0.22);
    border-radius: 16px;
}}
QLabel#badge {{
    color: #7fe3b6; font-size: 11px; font-weight: 700; letter-spacing: 1px;
}}
QLabel#src {{ color: rgba(180,192,214,0.78); }}
QLabel#tgt {{ color: #ffffff; font-weight: 700; }}
"""
