"""深色主题样式表（LiveDub 3.0 视觉）。

设计原则
--------
* 4px 栅格：所有间距是 4 的倍数，卡片之间 10px、控件之间 8px。
* 三级表面：窗口底（渐变）→ 卡片 PANEL → 输入框 INPUT，靠明度差分层，
  不依赖阴影（QSS 不支持 box-shadow），只在少量卡片上用 QGraphicsDropShadowEffect。
* 一个强调色：蓝紫渐变（品牌 / 主按钮 / 选中态），语义色只用于状态
  （绿 = 对方 / 成功，蓝 = 我说 / 信息，琥珀 = 警告，红 = 危险）。
* 文字四级：标题 #e9edf6 → 正文 #c3cbdc → 次要 #8b95a9 → 弱 #626d82。
* 圆角统一：卡片 13px、输入框 / 按钮 8px、胶囊 11px。
"""
from __future__ import annotations

import pathlib

# ---------------------------------------------------------------- 资源路径
_ASSETS = (pathlib.Path(__file__).parent / "assets").as_posix()
ASSETS_DIR = pathlib.Path(__file__).parent / "assets"
ICON_PATH = ASSETS_DIR / "icon.png"

ARROW_DOWN = f"{_ASSETS}/chevron-down.svg"
ARROW_UP = f"{_ASSETS}/chevron-up.svg"
CHECK = f"{_ASSETS}/check.svg"
SWAP = f"{_ASSETS}/swap.svg"
REFRESH = f"{_ASSETS}/refresh.svg"
PLAY = f"{_ASSETS}/play.svg"
STOP = f"{_ASSETS}/stop.svg"

# ---------------------------------------------------------------- 设计令牌
BG = "#0a0c11"          # 窗口底色
BG_TOP = "#0e1219"      # 渐变顶部
BG_BOTTOM = "#08090e"   # 渐变底部
PANEL = "#141821"       # 卡片
PANEL_2 = "#1a1f2b"     # 抬起表面（胶囊 / 菜单）
PANEL_3 = "#202633"     # hover
INPUT = "#0d1118"       # 输入框
BORDER = "#1f2532"      # 1px 分隔线 / 卡片描边
BORDER_2 = "#2b3446"    # 控件描边
TEXT = "#e9edf6"
TEXT_2 = "#c3cbdc"
MUTED = "#8b95a9"
MUTED_2 = "#626d82"
ACCENT = "#4d7cff"
ACCENT_2 = "#8b5cf6"
SUCCESS = "#3ddc97"
INFO = "#5aa2ff"
WARN = "#f5b544"
DANGER = "#ff6b6b"

DARK_QSS = f"""
/* ================= 基础 ================= */
QWidget {{
    background: transparent;
    color: {TEXT};
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC";
    font-size: 13px;
    outline: none;
}}
QMainWindow, QDialog {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {BG_TOP}, stop:0.45 {BG}, stop:1 {BG_BOTTOM});
}}
QLabel {{ background: transparent; }}
QToolTip {{
    background: {PANEL_2}; color: {TEXT_2};
    border: 1px solid {BORDER_2}; border-radius: 6px;
    padding: 5px 8px; font-size: 12px;
}}

/* ================= 卡片 / 分隔 ================= */
QFrame#card {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 13px;
}}
QFrame#bar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {ACCENT}, stop:1 {ACCENT_2});
    border: none; border-radius: 2px;
}}
QFrame#hline {{ background: {BORDER}; border: none; min-height: 1px; max-height: 1px; }}
QFrame#savebar {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px;
}}
QLabel#card_title {{ color: #d5dcec; }}
QLabel#card_hint {{ color: {MUTED_2}; font-size: 11px; }}
QLabel#field_label {{ color: {MUTED}; font-size: 12px; }}
QLabel#tiny {{ color: {MUTED_2}; font-size: 11px; }}
QLabel#kbd {{
    color: #cfd8ea; font-size: 11px; font-weight: 700;
    background: #1a2130; border: 1px solid #2b3547; border-radius: 6px;
    padding: 3px 8px;
}}
QLabel#mono {{ font-family: "Consolas", "Microsoft YaHei UI"; }}

/* ================= 顶部 ================= */
QLabel#logo {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {ACCENT}, stop:1 {ACCENT_2});
    border-radius: 10px; color: #ffffff; font-size: 15px; font-weight: 800;
}}
QLabel#h1 {{ font-size: 19px; font-weight: 700; color: #ffffff; }}
QLabel#sub {{ color: {MUTED}; font-size: 12px; }}

QFrame#pill {{
    background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 13px;
}}
QFrame#pill[live="true"] {{
    background: rgba(61, 220, 151, 0.08);
    border-color: rgba(61, 220, 151, 0.30);
}}
QLabel#pill_txt {{ color: {MUTED}; font-size: 12px; }}
QFrame#pill[live="true"] QLabel#pill_txt {{ color: #a7e9c8; }}

/* ================= 选项卡 ================= */
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar {{ qproperty-drawBase: 0; background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {MUTED};
    border: 1px solid transparent; border-radius: 8px;
    padding: 6px 16px; margin-right: 4px; margin-bottom: 2px;
    font-size: 13px; font-weight: 600;
}}
QTabBar::tab:hover {{ color: {TEXT_2}; background: rgba(255, 255, 255, 0.035); }}
QTabBar::tab:selected {{
    color: #ffffff;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 rgba(77, 124, 255, 0.20), stop:1 rgba(139, 92, 246, 0.14));
    border: 1px solid rgba(96, 132, 255, 0.32);
}}
QTabBar::tab:selected:hover {{ color: #ffffff; }}

/* ================= 按钮 ================= */
QPushButton {{
    background: {PANEL_2};
    border: 1px solid {BORDER_2};
    border-radius: 8px;
    padding: 0 14px;
    min-height: 30px;
    color: #dbe2f0;
    font-weight: 500;
}}
QPushButton:hover {{ background: {PANEL_3}; border-color: #3a4459; color: #ffffff; }}
QPushButton:pressed {{ background: #171c26; }}
QPushButton:disabled {{
    color: #4e5567; background: #12151b; border-color: #1b212c;
}}

QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {ACCENT}, stop:1 {ACCENT_2});
    border: 1px solid rgba(255, 255, 255, 0.10);
    color: #ffffff; font-weight: 700; font-size: 13px;
    padding: 0 20px; min-height: 36px; border-radius: 9px;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #5d89ff, stop:1 #9a6dff);
}}
QPushButton#primary:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3f6ae6, stop:1 #7a4fe0);
}}
QPushButton#primary:disabled {{ color: #cfd6e6; background: #2a3140; border-color: #333b4d; }}
QPushButton#primary[running="true"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #e4585a, stop:1 #bb3f57);
    border-color: rgba(255, 255, 255, 0.08);
}}
QPushButton#primary[running="true"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #ef6769, stop:1 #c94c64);
}}

QPushButton#ghost {{
    background: transparent; border: 1px solid {BORDER_2}; color: {MUTED};
    padding: 0 12px; min-height: 30px;
}}
QPushButton#ghost:hover {{ color: #ffffff; border-color: #46527a; background: rgba(255, 255, 255, 0.03); }}
QPushButton#ghost:checked {{
    color: {TEXT}; border-color: rgba(96, 132, 255, 0.45);
    background: rgba(77, 124, 255, 0.14);
}}
QPushButton#ghost:checked:hover {{ background: rgba(77, 124, 255, 0.20); }}

QPushButton#link {{
    background: transparent; border: none; color: {MUTED_2};
    padding: 0 4px; min-height: 20px; font-size: 12px;
}}
QPushButton#link:hover {{ color: {ACCENT}; background: transparent; }}

QPushButton#icon {{
    background: {INPUT}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 0;
}}
QPushButton#icon:hover {{ border-color: {BORDER_2}; background: #121722; }}

QPushButton#swap {{
    background: {INPUT}; border: 1px solid {BORDER};
    border-radius: 9px; padding: 0;
}}
QPushButton#swap:hover {{ border-color: rgba(96, 132, 255, 0.55); background: #10141f; }}

/* ================= 输入控件 ================= */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 0 10px;
    min-height: 30px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: #2f394d;
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: rgba(96, 132, 255, 0.75);
    background: #0e131d;
}}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled {{ color: #5b6374; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ border: none; width: 26px; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url({ARROW_DOWN}); width: 12px; height: 12px; }}
QComboBox::down-arrow:on {{ image: url({ARROW_UP}); }}
QComboBox QAbstractItemView {{
    background: {PANEL_2}; border: 1px solid {BORDER_2}; border-radius: 8px;
    selection-background-color: rgba(77, 124, 255, 0.22);
    selection-color: #ffffff;
    padding: 5px; outline: none;
}}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; border-radius: 6px; }}

QSpinBox, QDoubleSpinBox {{ padding-right: 20px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: transparent; border: none; width: 16px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right; margin-top: 3px; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 3px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({ARROW_UP}); width: 9px; height: 9px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({ARROW_DOWN}); width: 9px; height: 9px; }}

/* ================= 复选框 ================= */
QCheckBox {{ spacing: 8px; color: {TEXT_2}; font-size: 12px; }}
QCheckBox:hover {{ color: #ffffff; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid #3a4459; background: {INPUT};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {ACCENT}, stop:1 {ACCENT_2});
    border: 1px solid rgba(255, 255, 255, 0.14);
    image: url({CHECK});
}}
QCheckBox:disabled {{ color: #5b6374; }}

/* ================= 列表 / 历史 ================= */
QListWidget {{ background: transparent; border: none; outline: none; padding: 0; }}
QListWidget::item {{ border: none; margin: 0; padding: 0; }}
QListWidget::item:selected {{ background: transparent; }}

QFrame#hist {{
    background: #11151d; border: 1px solid #1d2431; border-radius: 9px;
}}
QFrame#hist:hover {{ background: #131823; border-color: #262f40; }}
QFrame#hist[dir="in"] {{ border-left: 2px solid {SUCCESS}; }}
QFrame#hist[dir="out"] {{ border-left: 2px solid {INFO}; }}
QLabel#hist_tag {{
    font-size: 10px; font-weight: 700; padding: 0 5px;
    border-radius: 5px; min-height: 15px;
}}
QLabel#hist_tag[dir="in"] {{ color: {SUCCESS}; background: rgba(61, 220, 151, 0.10); }}
QLabel#hist_tag[dir="out"] {{ color: {INFO}; background: rgba(90, 162, 255, 0.10); }}
QLabel#hist_src {{ color: {MUTED}; font-size: 12px; }}
QLabel#hist_tgt {{ color: #edf1f9; font-size: 13px; font-weight: 600; }}
QLabel#hist_time {{ color: #5a6479; font-size: 10px; font-family: "Consolas"; }}

QFrame#empty {{
    background: rgba(255, 255, 255, 0.014);
    border: 1px dashed #232b39; border-radius: 9px;
}}
QLabel#empty_title {{ color: {MUTED}; font-size: 12px; font-weight: 600; }}
QLabel#empty_sub {{ color: #56607a; font-size: 11px; }}

/* ================= 实时区 ================= */
QLabel#live_src {{ color: #93a0b8; font-size: 13px; }}
QLabel#live_tgt {{ color: #ffffff; font-size: 23px; font-weight: 700; }}
QLabel#live_badge {{
    color: {MUTED_2}; font-size: 11px; padding: 1px 8px;
    border: 1px solid {BORDER}; border-radius: 8px;
    background: #10141c;
}}
QLabel#live_badge[state="on"] {{
    color: #8fe8c0; border-color: rgba(61, 220, 151, 0.35);
    background: rgba(61, 220, 151, 0.08);
}}
QLabel#live_badge[state="busy"] {{
    color: #f7cd7a; border-color: rgba(245, 181, 68, 0.35);
    background: rgba(245, 181, 68, 0.08);
}}
QLabel#live_badge[state="error"] {{
    color: #ff9d9d; border-color: rgba(255, 107, 107, 0.35);
    background: rgba(255, 107, 107, 0.08);
}}
QLabel#count_badge {{
    color: {MUTED}; font-size: 10px; font-family: "Consolas";
    background: #10141c; border: 1px solid {BORDER};
    border-radius: 8px; padding: 0 6px; min-height: 16px;
}}

/* ================= 底部指标 ================= */
QLabel#chip {{
    color: #97a2b7; font-size: 11px;
    font-family: "Consolas", "Microsoft YaHei UI";
    background: #10141c; border: 1px solid #1d2431;
    border-radius: 11px; padding: 3px 10px;
}}
QLabel#chip[hot="true"] {{
    color: #86ecc2; border-color: rgba(61, 220, 151, 0.32);
    background: rgba(61, 220, 151, 0.07);
}}
QLabel#stat {{ color: {MUTED_2}; font-size: 11px; }}
QLabel#warn {{ color: {WARN}; font-size: 11px; }}
QLabel#ok {{ color: {SUCCESS}; font-size: 11px; }}
QLabel#hint {{ color: {MUTED}; font-size: 12px; }}

/* ================= 说明页 ================= */
QLabel#help {{ color: #aeb8ca; font-size: 12px; }}
QLabel#step_title {{ color: #eef2fa; font-size: 13px; font-weight: 600; }}
QLabel#step_num {{
    color: #a9bdff; font-size: 11px; font-weight: 700;
    background: rgba(77, 124, 255, 0.14);
    border: 1px solid rgba(96, 132, 255, 0.30);
    border-radius: 9px;
}}
QLabel#dot {{ color: {ACCENT}; font-size: 13px; }}

/* ================= 菜单 / 滚动条 ================= */
QMenu {{
    background: {PANEL_2}; border: 1px solid {BORDER_2};
    border-radius: 8px; padding: 5px;
}}
QMenu::item {{ padding: 6px 20px 6px 14px; border-radius: 6px; color: {TEXT_2}; }}
QMenu::item:selected {{ background: rgba(77, 124, 255, 0.20); color: #ffffff; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px 2px 2px 0; }}
QScrollBar::handle:vertical {{ background: #2a3242; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a465c; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 0 2px 2px 2px; }}
QScrollBar::handle:horizontal {{ background: #2a3242; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
"""

OVERLAY_QSS = f"""
QFrame#card {{
    background: rgba(14, 17, 24, {int(255 * 0.90)});
    border: 1px solid rgba(120, 150, 255, 0.20);
    border-radius: 16px;
}}
QLabel#badge {{
    color: #7fe3b6; font-size: 11px; font-weight: 700; letter-spacing: 1px;
}}
QLabel#src {{ color: rgba(180, 192, 214, 0.78); }}
QLabel#tgt {{ color: #ffffff; font-weight: 700; }}
"""
