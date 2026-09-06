"""Windows teacher launcher. --headless is useful for local integration tests."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import threading
import webbrowser

from classroom.core.config import prepare_data
from classroom.web.app import create_app
from classroom.version import VERSION


def lan_addresses():
    addresses = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip != "0.0.0.0":
                addresses.add(ip)
    except OSError:
        pass
    return sorted(addresses)


class InstanceLock:
    def __init__(self, root):
        import msvcrt
        self.handle = open(root / ".instance.lock", "a+b")
        self.handle.seek(0)
        if not self.handle.read(1):
            self.handle.write(b"1")
            self.handle.flush()
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.handle.close()
            raise RuntimeError("课堂助手已在运行，请使用已有的启动窗口。")

    def close(self):
        import msvcrt
        self.handle.seek(0)
        msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        self.handle.close()


def main():
    parser = argparse.ArgumentParser(description="课堂助手")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    lock = None
    server = None
    try:
        root, _, configured_port = prepare_data(args.data_dir)
        lock = InstanceLock(root)
        app = create_app(root)
        port = args.port or configured_port
        if not 1024 <= port <= 65535:
            raise ValueError("端口须为 1024—65535 的整数")
        urls = [f"http://{address}:{port}/" for address in lan_addresses()]
        app.config["STUDENT_URLS"] = urls
        admin = f'http://127.0.0.1:{port}/teacher?key={app.config["BOOTSTRAP_KEY"]}'
        from waitress import create_server
        try:
            server = create_server(app, host="0.0.0.0", port=port, threads=12,
                                   connection_limit=150, channel_timeout=30,
                                   max_request_body_size=16384)
        except OSError as error:
            raise RuntimeError(f"无法使用端口 {port}，可能已被占用。请修改数据目录的 settings.json 中 port 后重启。\n{error}")
        if args.headless:
            print(json.dumps({"admin_url": admin, "student_urls": urls, "data_dir": str(root)}, ensure_ascii=True), flush=True)
            server.run()
        else:
            threading.Thread(target=server.run, daemon=True).start()
            show_window(root, urls, admin, args.no_browser)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        if args.headless:
            raise
        import tkinter as tk
        from tkinter import messagebox
        window = tk.Tk()
        window.withdraw()
        messagebox.showerror("课堂助手无法启动", str(error), parent=window)
        window.destroy()
    finally:
        if server:
            server.close()
            server.task_dispatcher.shutdown()
        if lock:
            lock.close()


def show_window(root, urls, admin, no_browser):
    import tkinter as tk
    from tkinter import messagebox
    win = tk.Tk()
    win.title("课堂助手 v" + VERSION + " · 教师机")
    win.geometry("650x445")
    win.minsize(620, 420)
    win.configure(bg="#f1f4f6")
    font = ("Microsoft YaHei", 10)
    frame = tk.Frame(win, bg="#f1f4f6", padx=28, pady=22)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="课堂助手正在运行", font=("Microsoft YaHei", 20, "bold"), bg="#f1f4f6", fg="#176d61").pack(anchor="w")
    tk.Label(frame, text="1. 打开教师管理，选择班级并开始登记。\n2. 通过极域统一打开下方学生网址。\n3. 登记结束后，在教师管理中导出 Excel。", justify="left", font=font, bg="#f1f4f6", pady=14).pack(anchor="w")
    tk.Button(frame, text="打开教师管理", command=lambda: webbrowser.open(admin), bg="#176d61", fg="white", font=font, padx=20, pady=8, relief="flat").pack(anchor="w")
    tk.Label(frame, text="学生访问网址（多个地址时，请先从一台学生机测试）", font=font, bg="#f1f4f6", pady=9).pack(anchor="w")
    value = tk.StringVar(value=urls[0] if urls else "未检测到局域网地址，请检查网络后重启")
    from tkinter import ttk
    box = ttk.Combobox(frame, textvariable=value, values=urls, state="readonly", font=font)
    box.pack(fill="x")
    def copy_address():
        win.clipboard_clear()
        win.clipboard_append(value.get())
    controls = tk.Frame(frame, bg="#f1f4f6")
    controls.pack(fill="x", pady=10)
    tk.Button(controls, text="复制学生网址", font=font, command=copy_address).pack(side="left", padx=(0, 12))
    tk.Button(controls, text="打开数据目录", font=font, command=lambda: os.startfile(root)).pack(side="left")
    tk.Label(frame, text="上课期间请保留此窗口，可最小化。关闭窗口会停止学生访问。\n数据保存在本机，升级程序不会覆盖。", justify="left", font=("Microsoft YaHei", 9), bg="#f1f4f6", fg="#657985").pack(anchor="w", pady=8)
    def stop():
        if messagebox.askyesno("停止课堂助手", "关闭后学生将无法继续登记，已有数据保留。确认关闭？", parent=win):
            win.destroy()
    win.protocol("WM_DELETE_WINDOW", stop)
    if not no_browser:
        win.after(400, lambda: webbrowser.open(admin))
    win.mainloop()


if __name__ == "__main__":
    main()
