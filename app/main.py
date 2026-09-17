import sys, os, json, time, ctypes
from ctypes import wintypes
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPoint
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QLabel, QSystemTrayIcon, QMenu, QCheckBox, QComboBox, QDialog,
    QListWidget, QListWidgetItem, QMessageBox, QInputDialog, QGroupBox, QStyle
)

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
        try: user32.SetForegroundWindow(hwnd)
        except Exception: pass

def get_process_info(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = '未知程序'
    path = ''
    h = kernel32.OpenProcess(0x1000 | 0x0400, False, pid.value)
    if h:
        try:
            buf = ctypes.create_unicode_buffer(32768); size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                path = buf.value
                name = os.path.basename(path) or name
        finally:
            kernel32.CloseHandle(h)
    return pid.value, name, path

def enum_windows():
    arr=[]
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            cls=ctypes.create_unicode_buffer(256); user32.GetClassNameW(hwnd, cls, 256)
            arr.append((hwnd, cls.value))
        return True
    user32.EnumWindows(EnumProc(cb), 0); return arr

def find_context_menu():
    for hwnd, cls in enum_windows():
        if cls == '#32768':
            r=RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                if r.right-r.left > 20 and r.bottom-r.top > 10:
                    return hwnd, (r.left,r.top,r.right,r.bottom)
    return None, None

def paste_text(text, target_hwnd):
    if not text: return
    try:
        import pyperclip
        old = None
        try: old = pyperclip.paste()
        except Exception: pass
        pyperclip.copy(text)
        set_foreground(target_hwnd)
        time.sleep(0.10)
        user32.keybd_event(0x11, 0, 0, 0)
        user32.keybd_event(0x56, 0, 0, 0)
        user32.keybd_event(0x56, 0, 2, 0)
        user32.keybd_event(0x11, 0, 2, 0)
        if old is not None:
            time.sleep(0.08); pyperclip.copy(old)
    except Exception as e:
        print('paste error:', e)

class Bridge(QObject):
    right_clicked = Signal(int, int, int, str, str)

class InputPanel(QWidget):
    chosen = Signal(str)
    def __init__(self):
        super().__init__()
        self.items=[]
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet('''
            QWidget { background:#111111; color:#ffffff; border:1px solid #555555; border-radius:7px; }
            QLabel { border:none; color:#ffffff; font-weight:bold; padding:3px 6px; }
            QPushButton { background:#222222; color:#ffffff; border:1px solid #444444; border-radius:5px; padding:7px 12px; text-align:left; }
            QPushButton:hover { background:#333333; border:1px solid #777777; }
        ''')
        self.layout = QVBoxLayout(self); self.layout.setContentsMargins(7,7,7,7); self.layout.setSpacing(5)
        self.rebuild()
    def rebuild(self):
        while self.layout.count():
            w=self.layout.takeAt(0).widget()
            if w: w.deleteLater()
        title=QLabel('预置输入'); self.layout.addWidget(title)
        for item in self.items:
            b=QPushButton(item); b.setToolTip(item)
            b.clicked.connect(lambda checked=False, s=item: self.chosen.emit(s))
            self.layout.addWidget(b)
        self.adjustSize()

class SettingsDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner); self.owner=owner
        self.setWindowTitle(APP_NAME + ' - 设置'); self.resize(760,520)
        self.setStyleSheet('''QDialog{background:#202020;color:#fff;} QLabel{color:#fff;} QLineEdit,QListWidget,QComboBox{background:#111;color:#fff;border:1px solid #555;padding:5px;} QPushButton{padding:7px 12px;} QGroupBox{color:#fff;}''')
        root=QVBoxLayout(self)
        root.addWidget(QLabel('每个 Windows 程序单独保存一套预置输入。默认全部关闭。'))
        main=QHBoxLayout(); root.addLayout(main)
        left=QVBoxLayout(); main.addLayout(left,1)
        left.addWidget(QLabel('已配置程序'))
        self.apps=QListWidget(); left.addWidget(self.apps)
        hb=QHBoxLayout();
        add=QPushButton('添加程序'); add.clicked.connect(self.add_program)
        remove=QPushButton('删除程序'); remove.clicked.connect(self.remove_program)
        hb.addWidget(add); hb.addWidget(remove); left.addLayout(hb)
        right=QVBoxLayout(); main.addLayout(right,1)
        self.info=QLabel('选择程序后编辑'); right.addWidget(self.info)
        self.enable=QCheckBox('在此程序中启用右键预输入'); self.enable.stateChanged.connect(self.save_current); right.addWidget(self.enable)
        right.addWidget(QLabel('预置内容（每行一条）'))
        self.editor=QListWidget(); self.editor.setSelectionMode(QListWidget.SingleSelection); right.addWidget(self.editor)
        eb=QHBoxLayout(); self.newtext=QLineEdit(); self.newtext.setPlaceholderText('输入一条预置内容');
        ea=QPushButton('添加'); ea.clicked.connect(self.add_item); ed=QPushButton('删除'); ed.clicked.connect(self.delete_item); eu=QPushButton('修改'); eu.clicked.connect(self.edit_item)
        eb.addWidget(self.newtext); eb.addWidget(ea); eb.addWidget(ed); eb.addWidget(eu); right.addLayout(eb)
        foot=QHBoxLayout(); root.addLayout(foot); foot.addStretch(); close=QPushButton('保存并关闭'); close.clicked.connect(self.accept); foot.addWidget(close)
        self.apps.currentRowChanged.connect(self.select_app)
        self.refresh()
    def refresh(self):
        self.apps.blockSignals(True); self.apps.clear()
        for key,data in self.owner.programs.items():
            label=data.get('name') or os.path.basename(key) or key
            item=QListWidgetItem(label); item.setData(Qt.UserRole,key); self.apps.addItem(item)
        self.apps.blockSignals(False)
        if self.apps.count(): self.apps.setCurrentRow(0)
        else: self.clear_editor()
    def clear_editor(self): self.info.setText('暂无程序配置'); self.enable.setChecked(False); self.editor.clear()
    def select_app(self,row):
        if row<0: return self.clear_editor()
        key=self.apps.item(row).data(Qt.UserRole); d=self.owner.programs.get(key,{})
        self.current_key=key; self.info.setText((d.get('name') or os.path.basename(key)) + '\n' + key)
        self.enable.blockSignals(True); self.enable.setChecked(bool(d.get('enabled',False))); self.enable.blockSignals(False)
        self.editor.clear(); self.editor.addItems(d.get('items',[]))
    def save_current(self):
        if not hasattr(self,'current_key') or self.current_key not in self.owner.programs: return
        self.owner.programs[self.current_key]['enabled']=self.enable.isChecked(); self.owner.save()
    def add_program(self):
        path,ok=QInputDialog.getText(self,'添加程序','程序 EXE 完整路径（也可以填写唯一程序名）：')
        if not ok or not path.strip(): return
        key=path.strip(); name=os.path.basename(key) or key
        if key not in self.owner.programs: self.owner.programs[key]={'name':name,'enabled':False,'items':[]}
        self.owner.save(); self.refresh();
        for i in range(self.apps.count()):
            if self.apps.item(i).data(Qt.UserRole)==key: self.apps.setCurrentRow(i); break
    def remove_program(self):
        row=self.apps.currentRow()
        if row<0:return
        key=self.apps.item(row).data(Qt.UserRole)
        if QMessageBox.question(self,'确认','删除这个程序的独立预置配置？')==QMessageBox.Yes:
            self.owner.programs.pop(key,None); self.owner.save(); self.refresh()
    def add_item(self):
        if not hasattr(self,'current_key'): return
        s=self.newtext.text().strip()
        if not s:return
        d=self.owner.programs[self.current_key]; d.setdefault('items',[])
        if s not in d['items']: d['items'].append(s)
        self.newtext.clear(); self.owner.save(); self.select_app(self.apps.currentRow())
    def delete_item(self):
        if not hasattr(self,'current_key'): return
        row=self.editor.currentRow()
        if row>=0:
            self.owner.programs[self.current_key]['items'].pop(row); self.owner.save(); self.select_app(self.apps.currentRow())
    def edit_item(self):
        if not hasattr(self,'current_key'): return
        row=self.editor.currentRow()
        if row<0:return
        old=self.editor.item(row).text(); s,ok=QInputDialog.getText(self,'修改预置内容','内容：',text=old)
        if ok and s.strip(): self.owner.programs[self.current_key]['items'][row]=s.strip(); self.owner.save(); self.select_app(self.apps.currentRow())

class App(QObject):
    def __init__(self):
        super().__init__(); self.programs={}; self.global_items=[]; self.enabled=True; self.load(); self.target_hwnd=0; self.target_key=''
        self.panel=InputPanel(); self.panel.chosen.connect(self.select)
        self.bridge=Bridge(); self.bridge.right_clicked.connect(self.on_right)
        self.listener=None; self.settings=None
        self.start_listener(); self.setup_tray()
    def load(self):
        default=['测试内容','请填写','已确认']
        try:
            with open(CONFIG,'r',encoding='utf-8') as f: d=json.load(f)
            self.programs=d.get('programs',{}); self.global_items=d.get('global_items',default); self.enabled=d.get('enabled',True)
        except Exception: self.programs={}; self.global_items=default; self.enabled=True
    def save(self):
        try:
            with open(CONFIG,'w',encoding='utf-8') as f: json.dump({'programs':self.programs,'global_items':self.global_items,'enabled':self.enabled},f,ensure_ascii=False,indent=2)
        except Exception as e: print('save error',e)
    def setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        icon_path = os.path.join(BASE_DIR, "app.ico")
        if os.path.exists(icon_path):
            self.tray.setIcon(QIcon(icon_path))
        else:
            self.tray.setIcon(QApplication.style().standardIcon(QStyle.SP_ComputerIcon))
        self.tray.setToolTip(APP_NAME)

        self.menu = QMenu()
        self.action_settings = QAction("设置", self)
        self.action_settings.triggered.connect(self.open_settings)
        self.action_exit = QAction("退出", self)
        self.action_exit.triggered.connect(self.quit)
        self.menu.addAction(self.action_settings)
        self.menu.addAction(self.action_exit)
        self.tray.setContextMenu(self.menu)
        self.tray.show()
        self.tray.setVisible(True)

    def update_toggle_text(self):
        self.toggle_action.setText('关闭所有程序的右键预输入' if self.enabled else '开启所有程序的右键预输入')
    def start_listener(self):
        from pynput import mouse
        def on_click(x,y,button,pressed):
            if pressed and button == mouse.Button.right:
                hwnd=get_foreground(); pid,name,path=get_process_info(hwnd)
                self.target_hwnd=hwnd; self.target_key=path or name
                self.bridge.right_clicked.emit(x,y,pid,name,path)
        self.listener=mouse.Listener(on_click=on_click); self.listener.daemon=True; self.listener.start()
    def on_right(self,x,y,pid,name,path):
        if not self.enabled: return
        d=self.programs.get(path) if path else None
        if not d or not d.get('enabled',False) or not d.get('items'): return
        self.panel.items=list(d.get('items',[])); self.panel.rebuild()
        QTimer.singleShot(100, lambda: self.show_panel(x,y))
    def show_panel(self,x,y):
        _, rect=find_context_menu(); screen=QApplication.screenAt(QPoint(x,y)) or QApplication.primaryScreen(); geo=screen.availableGeometry(); w=self.panel.sizeHint().width(); h=self.panel.sizeHint().height(); gap=8
        if rect:
            l,t,r,b=rect
            # 首选：原生右键菜单的右上方，不遮挡原菜单
            if r+w+gap <= geo.right() and t-h-gap >= geo.top(): px,py=r+gap,t-h-gap
            elif l-w-gap >= geo.left() and t-h-gap >= geo.top(): px,py=l-w-gap,t-h-gap
            elif r+w+gap <= geo.right(): px,py=r+gap,max(geo.top(),min(t,geo.bottom()-h))
            else: px,py=max(geo.left(),l-w-gap),max(geo.top(),min(t,geo.bottom()-h))
        else:
            px=min(x+180,geo.right()-w); py=max(geo.top(),y-h-12)
        self.panel.move(px,py); self.panel.show()
    def select(self,text):
        self.panel.hide(); QApplication.processEvents(); paste_text(text,self.target_hwnd)
    def open_settings(self):
        if self.settings is None: self.settings=SettingsDialog(self)
        self.settings.refresh(); self.settings.show(); self.settings.raise_(); self.settings.activateWindow()
    def toggle_all(self): self.enabled=not self.enabled; self.save(); self.update_toggle_text()
    def reload(self): self.load(); self.update_toggle_text()
    def quit(self):
        try:self.listener.stop()
        except:pass
        self.panel.close(); self.tray.hide(); QApplication.quit()

if __name__=='__main__':
    app=QApplication(sys.argv); app.setQuitOnLastWindowClosed(False)
    a=App(); sys.exit(app.exec())
