# 预置输入助手

Windows 小工具：监听鼠标右键，在 Windows 原生右键菜单外侧显示可自定义的预置文本。点击某条文本后，会把文本粘贴到右键前仍然处于输入状态的窗口/输入框。

## 特点
- 不替换、不修改 Windows 原生右键菜单。
- 自动寻找当前 Windows 原生菜单位置，快捷输入面板放在菜单外侧，尽量不遮挡。
- 预置内容可以自己添加、修改、删除。
- 支持中文、英文、数字、符号，因为采用剪贴板粘贴而不是键盘逐字模拟。
- 托盘菜单可以设置和启停。
- 配置保存在程序目录 `config.json`。

## 本地运行
```bash
pip install -r requirements.txt
python app/main.py
```

## GitHub Actions
进入 Actions，手动运行 `Build Windows`，完成后下载 `预置输入助手-Windows` artifact。生成的是 onedir 目录，启动 `预置输入助手.exe`。
