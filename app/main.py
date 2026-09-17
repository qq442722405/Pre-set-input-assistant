import sys, os, json, time, ctypes, threading
from ctypes import wintypes
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPoint
from PySide6.QtGui import QFont, QAction
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QSystemTrayIcon, QMenu, QMessageBox

APP_NAME = '预置输入助手'
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG = os.path.join(BASE_DIR, 'config.json')

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

class POINT(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]

class RECT(ctypes.Structure):
    _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG), ('right', wintypes.LONG), ('bottom', wintypes.LONG)]

def get_cursor():
    p = POINT(); user32.GetCursorPos(ctypes.byref(p)); return p.x, p.y

def get_foreground():
    return user32.GetForegroundWindow()

def set_foreground(hwnd):
    if hwnd:
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)

def enum_windows():
    arr=[]
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            cls=ctypes.create_unicode_buffer(256); user32.GetClassNameW(hwnd, cls, 256)
            arr.append((hwnd, cls.value))
        return True
    user32.EnumWindows(EnumProc(cb), 0)
    return arr

def find_context_menu():
    # Standard Windows popup menus generally use #32768.
    for hwnd, cls in enum_windows():
        if cls == '#32768':
            r=RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                if r.right-r.left > 20 and r.bottom-r.top > 10:
                    return hwnd, (r.left,r.top,r.right,r.bottom)
    return None, None

def paste_text(text, target_hwnd):
    if not text:
        return
    try:
        import pyperclip
        old = None
        try: old = pyperclip.paste()
        except Exception: pass
        pyperclip.copy(text)
        # Dismiss native menu and return focus to the original target.
        set_foreground(target_hwnd)
        time.sleep(0.08)
        user32.keybd_event(0x11, 0, 0, 0) # Ctrl down
        user32.keybd_event(0x56, 0, 0, 0) # V down
        user32.keybd_event(0x56, 0, 2, 0)
        user32.keybd_event(0x11, 0, 2, 0)
        if old is not None:
            time.sleep(0.08)
            pyperclip.copy(old)
    except Exception as e:
        print('paste error:', e)

class Bridge(QObject):
    right_clicked = Signal(int,int)

class InputPanel(QWidget):
    chosen = Signal(str)
    def __init__(self, items):
        super().__init__()
        self.items = items
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet('QWidget{background:#ffffff;border:1px solid #b8b8b8;border-radius:6px;} QPushButton{background:#f7f7f7;border:1px solid #d0d0d0;border-radius:4px;padding:7px 10px;text-align:left;} QPushButton:hover{background:#e8f2ff;}')
        self.layout = QVBoxLayout(self); self.layout.setContentsMargins(7,7,7,7); self.layout.setSpacing(5)
        self.rebuild()
    def rebuild(self):
        while self.layout.count():
            w=self.layout.takeAt(0).widget()
            if w: w.deleteLater()
        title=QLabel('预置输入')
        title.setStyleSheet('border:none;font-weight:bold;padding:2px 4px;color:#333;')
        self.layout.addWidget(title)
        for item in self.items:
            b=QPushButton(item)
            b.setToolTip(item)
            b.clicked.connect(lambda checked=False, s=item: self.chosen.emit(s))
            self.layout.addWidget(b)
        self.adjustSize()

class Settings(QWidget):
    changed=Signal()
    def __init__(self, owner):
        super().__init__(); self.owner=owner
        self.setWindowTitle('预置输入助手 - 设置'); self.resize(520,430)
        root=QVBoxLayout(self)
        root.addWidget(QLabel('预置内容（每行一条，右键后会显示在原生菜单旁边）'))
        self.editor=QLineEdit(); self.editor.setPlaceholderText('例如：张三')
        root.addWidget(self.editor)
        self.list_label=QLabel('当前内容')
        root.addWidget(self.list_label)
        self.rows=QVBoxLayout(); root.addLayout(self.rows)
        h=QHBoxLayout(); add=QPushButton('添加'); add.clicked.connect(self.add); save=QPushButton('保存'); save.clicked.connect(self.save); h.addWidget(add); h.addWidget(save); root.addLayout(h)
        root.addWidget(QLabel('说明：点击右键时，本助手只在原生右键菜单外侧显示快捷输入项，不替换系统右键菜单。'))
        self.refresh()
    def refresh(self):
        while self.rows.count():
            w=self.rows.takeAt(0).widget()
            if w: w.deleteLater()
        for i,s in enumerate(self.owner.items):
            row=QWidget(); lay=QHBoxLayout(row); lay.setContentsMargins(0,0,0,0)
            e=QLineEdit(s); d=QPushButton('删除'); d.clicked.connect(lambda _,i=i:self.delete(i)); lay.addWidget(e); lay.addWidget(d); self.rows.addWidget(row)
    def add(self):
        s=self.editor.text().strip()
        if s and s not in self.owner.items: self.owner.items.append(s); self.editor.clear(); self.refresh()
    def delete(self,i):
        if 0<=i<len(self.owner.items): self.owner.items.pop(i); self.refresh()
    def save(self): self.owner.save(); self.owner.panel.items=self.owner.items; self.owner.panel.rebuild(); self.changed.emit(); self.close()

class App(QObject):
    def __init__(self):
        super().__init__(); self.items=[]; self.load(); self.target_hwnd=0; self.panel=InputPanel(self.items)
        self.panel.chosen.connect(self.select)
        self.bridge=Bridge(); self.bridge.right_clicked.connect(self.on_right)
        self.listener=None
        self.settings=None
        self.start_listener()
        self.tray=QSystemTrayIcon()
        self.tray.setToolTip(APP_NAME)
        self.menu=QMenu(); a=QAction('设置预置内容'); a.triggered.connect(self.open_settings); self.menu.addAction(a)
        a2=QAction('隐藏/显示右键快捷输入'); a2.triggered.connect(self.toggle); self.menu.addAction(a2)
        self.menu.addSeparator(); aq=QAction('退出'); aq.triggered.connect(QApplication.quit); self.menu.addAction(aq)
        self.tray.setContextMenu(self.menu); self.tray.show(); self.enabled=True
    def load(self):
        default=['测试内容','请填写','已确认']
        try:
            with open(CONFIG,'r',encoding='utf-8') as f: d=json.load(f); self.items=d.get('items',default); self.enabled=d.get('enabled',True)
        except Exception: self.items=default; self.enabled=True
    def save(self):
        with open(CONFIG,'w',encoding='utf-8') as f: json.dump({'items':self.items,'enabled':self.enabled},f,ensure_ascii=False,indent=2)
    def start_listener(self):
        from pynput import mouse
        def on_click(x,y,button,pressed):
            if pressed and button == mouse.Button.right:
                hwnd=get_foreground()
                self.target_hwnd=hwnd
                self.bridge.right_clicked.emit(x,y)
        self.listener=mouse.Listener(on_click=on_click); self.listener.daemon=True; self.listener.start()
    def on_right(self,x,y):
        if not self.enabled or not self.items: return
        # Give Windows time to create its native context menu, then place our panel outside it.
        QTimer.singleShot(90, lambda: self.show_panel(x,y))
    def show_panel(self,x,y):
        if not self.enabled: return
        _, rect=find_context_menu()
        if rect:
            l,t,r,b=rect
            # Prefer the side with more room. Keep a small gap so the native menu remains unobstructed.
            screen=QApplication.screenAt(QPoint(x,y)) or QApplication.primaryScreen(); geo=screen.availableGeometry()
            gap=8; w=self.panel.sizeHint().width(); h=self.panel.sizeHint().height()
            if r+w+gap <= geo.right(): px=r+gap
            else: px=l-w-gap
            py=max(geo.top(), min(y, geo.bottom()-h))
        else:
            screen=QApplication.screenAt(QPoint(x,y)) or QApplication.primaryScreen(); geo=screen.availableGeometry(); w=self.panel.sizeHint().width(); h=self.panel.sizeHint().height(); px=min(x+220,geo.right()-w); py=min(y,geo.bottom()-h)
        self.panel.move(px,py); self.panel.show()
    def select(self,text):
        self.panel.hide(); QApplication.processEvents(); paste_text(text,self.target_hwnd)
    def open_settings(self):
        if self.settings is None: self.settings=Settings(self)
        self.settings.refresh(); self.settings.show(); self.settings.raise_(); self.settings.activateWindow()
    def toggle(self):
        self.enabled=not self.enabled; self.save()
    def quit(self):
        try: self.listener.stop()
        except: pass
        QApplication.quit()

if __name__=='__main__':
    app=QApplication(sys.argv); app.setQuitOnLastWindowClosed(False)
    a=App(); sys.exit(app.exec())
