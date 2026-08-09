from __future__ import annotations


CYAN = "#4debf3"
CORAL = "#ff486d"
VOID = "#080b0c"
PANEL = "#0e1415"
PANEL_2 = "#121a1b"
LINE = "#263235"
TEXT = "#e7f0ec"
MUTED = "#83918c"


APP_STYLESHEET = f"""
QWidget {{
    color: {TEXT};
    background: {VOID};
    font-family: "Perfect DOS VGA 437 Win";
    font-size: 15px;
}}
QMainWindow {{ background: {VOID}; }}
QFrame#navRail {{ background: #0b1011; border-right: 1px solid {LINE}; }}
QFrame#sidebar {{ background: {PANEL}; border-right: 1px solid {LINE}; }}
QFrame#chatHeader {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
QFrame#composerFrame {{ background: #101718; border: 1px solid {LINE}; border-bottom: 2px solid {CYAN}; }}
QLabel#brand {{ font: 600 19px "Perfect DOS VGA 437 Win"; }}
QLabel#protocolLive {{ color: {CORAL}; font: 600 10px "Perfect DOS VGA 437 Win"; }}
QLabel#sectionCode {{ color: {CYAN}; font: 600 9px "Perfect DOS VGA 437 Win"; letter-spacing: 2px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#presence {{ color: {CYAN}; font: 10px "Perfect DOS VGA 437 Win"; }}
QLabel#networkStatus {{ color: {MUTED}; font: 9px "Perfect DOS VGA 437 Win"; }}
QLineEdit, QTextEdit, QComboBox {{
    color: {TEXT}; background: #0a0f10; border: 1px solid {LINE};
    padding: 9px 10px; selection-background-color: {CYAN}; selection-color: {VOID};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: {CYAN}; }}
QComboBox::drop-down {{ border: 0; width: 26px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; color: {TEXT}; selection-background-color: #18343a; }}
QCheckBox {{ color: {TEXT}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    background: #080d0e; border: 2px solid {CYAN};
}}
QCheckBox::indicator:hover {{ border-color: #bdfbff; background: #12282c; }}
QCheckBox::indicator:checked {{ background: {CYAN}; border: 2px solid #bdfbff; }}
QCheckBox::indicator:disabled {{ background: #111718; border-color: #405055; }}
QCheckBox:disabled {{ color: {MUTED}; }}
QPushButton {{ background: transparent; border: 0; padding: 8px; color: {MUTED}; }}
QPushButton:hover {{ color: {CYAN}; background: #172022; }}
QPushButton:checked {{ color: {CYAN}; border-left: 2px solid {CYAN}; background: #102024; }}
QPushButton#filter {{ font: 10px "Perfect DOS VGA 437 Win"; padding: 7px 10px; }}
QPushButton#filter:checked {{ color: {VOID}; background: {CORAL}; border: 0; }}
QPushButton#send {{ color: white; background: {CORAL}; font: 700 16px "Perfect DOS VGA 437 Win"; padding: 8px 13px; }}
QPushButton#send:hover {{ background: #ff6685; }}
QPushButton#createAction {{
    color: {CYAN};
    background-color: #101718;
    border: 1px solid {CYAN};
    font: 800 15px "Perfect DOS VGA 437 Win";
    padding: 2px;
}}
QPushButton#createAction:hover {{
    color: #d9fdff;
    background-color: #18343a;
    border: 2px solid #76f4fa;
}}
QPushButton#createAction:pressed {{ color: white; background-color: #20515a; }}
QPushButton#groupAction {{
    color: {TEXT};
    background: transparent;
    border: 1px solid {LINE};
    font: 700 15px "Perfect DOS VGA 437 Win";
    padding: 6px 10px;
}}
QPushButton#groupAction:hover {{ color: {CYAN}; border-color: {CYAN}; background:#172022; }}
QListWidget {{ background: transparent; border: 0; outline: 0; }}
QListWidget::item {{ border-left: 2px solid transparent; }}
QListWidget::item:hover {{ background: {PANEL_2}; }}
QListWidget::item:selected {{ background: #102024; border-left: 2px solid {CYAN}; }}
QScrollArea {{ border: 0; background: transparent; }}
QScrollBar:vertical {{ background: #0a0f10; width: 7px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #294247; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{ color: {TEXT}; background: #11191b; border: 1px solid {CYAN}; padding: 5px; }}
"""
