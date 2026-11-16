import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------- 可配置项 ----------
FFMPEG = "ffmpeg"      # 若未加入 PATH，可改成绝对路径，如 r"D:\ffmpeg\bin\ffmpeg.exe"
FFPROBE = "ffprobe"    # 同上
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# 格式名 -> (扩展名, ffmpeg 编码参数)
FORMATS = {
    "MP3  音频":        ("mp3",  ["-c:a", "libmp3lame", "-b:a", "192k"]),
    "WAV  音频":        ("wav",  ["-c:a", "pcm_s16le"]),
    "M4A / AAC 音频":   ("m4a",  ["-c:a", "aac", "-b:a", "192k"]),
    "FLAC 无损音频":    ("flac", ["-c:a", "flac"]),
    "OGG 音频":         ("ogg",  ["-c:a", "libvorbis", "-q:a", "5"]),
    "MOV 容器（仅音频）": ("mov",  ["-c:a", "aac", "-b:a", "192k"]),
    "MP4 容器（仅音频）": ("mp4",  ["-c:a", "aac", "-b:a", "192k"]),
}

AUDIO_VIDEO_TYPES = (
    ("音视频文件", "*.mp3 *.wav *.flac *.aac *.m4a *.ogg *.wma *.opus "
                   "*.aiff *.amr *.mov *.mp4 *.mkv *.avi *.wmv *.webm *.flv"),
    ("所有文件", "*.*"),
)


def get_duration(path: str) -> float:
    """用 ffprobe 获取媒体时长（秒），失败返回 0。"""
    cmd = [FFPROBE, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             creationflags=CREATE_NO_WINDOW, timeout=15)
        text = out.stdout.strip()
        return float(text) if text and text != "N/A" else 0.0
    except Exception:
        return 0.0


class ConverterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc = None            # 当前 ffmpeg 进程
        self.duration = 0.0         # 源文件时长（秒）
        self.busy = False

        root.title("音视频格式转换器 · FFmpeg GUI")
        root.geometry("700x540")
        root.minsize(620, 480)

        pad = {"padx": 8, "pady": 6}
        main = ttk.Frame(root, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(7, weight=1)

        # 1. 源文件
        ttk.Label(main, text="源文件：").grid(row=0, column=0, sticky="w", **pad)
        self.in_var = tk.StringVar()
        ttk.Entry(main, textvariable=self.in_var).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(main, text="浏览…", command=self.choose_input).grid(row=0, column=2, **pad)

        # 2. 目标格式
        ttk.Label(main, text="目标格式：").grid(row=1, column=0, sticky="w", **pad)
        self.fmt_var = tk.StringVar(value=list(FORMATS)[0])
        cb = ttk.Combobox(main, textvariable=self.fmt_var,
                          values=list(FORMATS), state="readonly")
        cb.grid(row=1, column=1, sticky="w", **pad)
        cb.bind("<<ComboboxSelected>>", self.on_format_change)

        # 3. 输出路径
        ttk.Label(main, text="输出到：").grid(row=2, column=0, sticky="w", **pad)
        self.out_var = tk.StringVar()
        ttk.Entry(main, textvariable=self.out_var).grid(row=2, column=1, sticky="ew", **pad)
        ttk.Button(main, text="另存为…", command=self.choose_output).grid(row=2, column=2, **pad)

        # 4. 额外参数
        ttk.Label(main, text="额外参数：").grid(row=3, column=0, sticky="w", **pad)
        self.extra_var = tk.StringVar()
        ttk.Entry(main, textvariable=self.extra_var).grid(row=3, column=1, columnspan=2,
                                                          sticky="ew", **pad)
        ttk.Label(main, text="可留空。例：-ar 44100 -q:a 2 -vn（-vn 可剔除视频轨）",
                  foreground="#888888").grid(row=4, column=1, columnspan=2, sticky="w", padx=8)

        # 5. 操作栏 + 进度条
        bar = ttk.Frame(main)
        bar.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(12, 4))
        bar.columnconfigure(1, weight=1)
        self.btn = ttk.Button(bar, text="开始转换", command=self.start)
        self.btn.grid(row=0, column=0, padx=(0, 12))
        self.pbar = ttk.Progressbar(bar, mode="determinate", maximum=100)
        self.pbar.grid(row=0, column=1, sticky="ew")
        self.pct_label = ttk.Label(bar, text="  0%", width=6)
        self.pct_label.grid(row=0, column=2)

        # 6. 日志区
        log_frame = ttk.LabelFrame(main, text="日志", padding=4)
        log_frame.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=sb.set)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log("就绪。请选择要转换的音视频文件。")
        self._check_ffmpeg()

    # ---------------- 工具方法 ----------------
    def log(self, msg: str):
        """线程安全地追加一行日志。"""
        def _do():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg.rstrip() + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(0, _do)

    def _check_ffmpeg(self):
        """启动时检查 ffmpeg 是否可用。"""
        try:
            subprocess.run([FFMPEG, "-version"], capture_output=True,
                           creationflags=CREATE_NO_WINDOW, timeout=10)
            self.log("✔ 已检测到 ffmpeg。")
        except Exception:
            self.log("✘ 未检测到 ffmpeg，请安装并加入系统 PATH，或修改脚本顶部的 FFMPEG/FFPROBE 路径。")

    def _set_busy(self, busy: bool):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.btn.configure(state=state)

    # ---------------- 事件 ----------------
    def choose_input(self):
        path = filedialog.askopenfilename(title="选择源文件", filetypes=AUDIO_VIDEO_TYPES)
        if not path:
            return
        self.in_var.set(path)
        # 自动生成输出路径（同目录，换扩展名）
        self.refresh_output_path()
        # 读取时长
        self.duration = get_duration(path)
        self.log(f"载入：{path}")
        if self.duration > 0:
            self.log(f"    时长约 {self.duration:.2f} 秒。")
        else:
            self.log("    未能读取时长，进度条将不显示百分比。")

    def choose_output(self):
        ext = FORMATS[self.fmt_var.get()][0]
        default_name = self._default_output_name()
        path = filedialog.asksaveasfilename(
            title="保存为",
            defaultextension=f".{ext}",
            initialfile=os.path.basename(default_name) if default_name else f"output.{ext}",
            filetypes=[(f"{ext.upper()} 文件", f"*.{ext}"), ("所有文件", "*.*")],
        )
        if path:
            self.out_var.set(path)

    def on_format_change(self, _event=None):
        self.refresh_output_path()

    def _default_output_name(self) -> str:
        src = self.in_var.get().strip()
        if not src:
            return ""
        ext = FORMATS[self.fmt_var.get()][0]
        base, _ = os.path.splitext(src)
        return f"{base}.{ext}"

    def refresh_output_path(self):
        if self.in_var.get().strip():
            self.out_var.set(self._default_output_name())

    # ---------------- 转换流程 ----------------
    def start(self):
        if self.busy:
            return
        src = self.in_var.get().strip()
        dst = self.out_var.get().strip()

        if not src or not os.path.isfile(src):
            messagebox.showwarning("提示", "请选择有效的源文件。")
            return
        if not dst:
            messagebox.showwarning("提示", "请指定输出文件路径。")
            return
        if os.path.abspath(src) == os.path.abspath(dst):
            messagebox.showerror("错误", "输入与输出不能是同一个文件。")
            return

        ext, codec_args = FORMATS[self.fmt_var.get()]
        extra = self.extra_var.get().strip().split()

        cmd = [FFMPEG, "-y", "-i", src,
               "-loglevel", "error", "-nostats",
               "-progress", "pipe:1"]
        cmd += codec_args + extra + [dst]

        self.log("─" * 48)
        self.log("执行命令：\n  " + " ".join(self._quote(c) for c in cmd))

        self.duration = get_duration(src)
        self.pbar["value"] = 0
        self.pct_label.configure(text="  0%")
        self._set_busy(True)

        threading.Thread(target=self._worker, args=(cmd,), daemon=True).start()

    @staticmethod
    def _quote(s: str) -> str:
        return f'"{s}"' if " " in s else s

    def _worker(self, cmd):
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
        except FileNotFoundError:
            self.root.after(0, self._finish, False, "找不到 ffmpeg，请确认已安装且加入 PATH。")
            return
        except Exception as e:
            self.root.after(0, self._finish, False, f"启动失败：{e}")
            return

        # 读取进度（stdout 输出 key=value 行）
        last_pct = -1
        for line in self.proc.stdout:
            line = line.strip()
            if line.startswith(("out_time_us=", "out_time_ms=")):
                val = line.split("=", 1)[1]
                if val.isdigit() and self.duration > 0:
                    pct = min(100, int(int(val) / 1_000_000 / self.duration * 100))
                    if pct != last_pct:
                        last_pct = pct
                        self.root.after(0, self._update_progress, pct)
            elif line == "progress=end":
                self.root.after(0, self._update_progress, 100)

        self.proc.wait()
        ret = self.proc.returncode
        err = self.proc.stderr.read() if self.proc.stderr else ""

        ok = (ret == 0)
        self.root.after(0, self._finish, ok, err.strip() or f"ffmpeg 退出码 {ret}")

    def _update_progress(self, pct: int):
        self.pbar["value"] = pct
        self.pct_label.configure(text=f"{pct:3d}%")

    def _finish(self, ok: bool, message: str):
        self._set_busy(False)
        self.proc = None
        if ok:
            self.pbar["value"] = 100
            self.pct_label.configure(text="100%")
            self.log("✔ 转换完成 → " + self.out_var.get())
            messagebox.showinfo("完成", f"转换成功：\n{self.out_var.get()}")
        else:
            self.log("✘ 转换失败。")
            if message:
                self.log(message)
            messagebox.showerror("失败", "转换失败，详见日志。")

    def on_close(self):
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("确认", "正在转换中，确定要退出吗？"):
                return
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    # 用系统默认主题，看起来更现代
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    ConverterApp(root)
    root.mainloop()
