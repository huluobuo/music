import requests
import os
import json
import time
import logging
import pygame
import tkinter as tk
from tkinter import messagebox, ttk
from threading import Thread
from mutagen.mp3 import MP3

# 初始化pygame混音器
pygame.mixer.init()

class Music_main():
    """
        爬取音乐
    """
    def __init__(self, progress_callback=None):
        """初始化类变量"""
        self.music_list_url = "https://huluobuo.github.io/music/musiclist.json"
        self.music_list = []
        self.now_music_name = ""
        self.now_music_time_big = 0
        self.now_music_path = ""
        self.playing = False
        self.paused = False
        self.play_thread = None
        self.volume = 0.5
        self.local_dir = os.path.join(os.getcwd(), 'local')
        os.makedirs(self.local_dir, exist_ok=True)
        self.progress_callback = progress_callback

    def internet_check(self):
        """检查网络"""
        try:
            requests.get(self.music_list_url, verify=False)
        except requests.RequestException as e:
            logging.error("网络检查 - 网络链接错误或服务器失效，请检查网络！错误详情：%s" % str(e))
            return False
        else:
            logging.info("网络检查 - 网络正常！")
            return True

    def get_music_list(self):
        """获取音乐列表"""
        if not self.internet_check():
            return []
        try:
            music_list_json = requests.get(self.music_list_url, verify=False).text
        except requests.RequestException as e:
            logging.error("获取音乐列表 - 获取音乐列表失败！错误详情：%s" % str(e))
            return []
        else:
            self.music_list = json.loads(music_list_json)
            logging.info("获取音乐列表 - 获取音乐列表成功！")
        if len(self.music_list) == 0:
            logging.error("获取音乐列表 - 音乐列表为空！")
            return []
        try:
            for music in self.music_list:
                if type(music) != dict:
                    raise TypeError
                if "name" not in music:
                    raise KeyError
                if "time_big" not in music:
                    raise KeyError
                if "path" not in music:
                    raise KeyError
            return self.music_list
        except (TypeError, KeyError):
            logging.error("获取音乐列表 - 音乐列表格式错误！")
            return []

    def play_music(self, music_name):
        """播放音乐（先检查本地文件，不存在则下载）"""
        for music in self.music_list:
            if music["name"] == music_name:
                self.now_music_name = music_name
                music_url = music["path"].replace("./", "https://huluobuo.github.io/music/")
                local_filename = f"{music_name}.mp3"
                local_path = os.path.join(self.local_dir, local_filename)
                
                # 检查本地文件是否存在，不存在则下载
                if not os.path.exists(local_path):
                    if self.progress_callback:
                        self.progress_callback(0, f"准备下载 {music_name}...")
                    if not self.download_music(music_url, music_name):
                        logging.error(f"无法下载音乐: {music_name}")
                        return
                
                # 播放本地音乐文件
                try:
                    pygame.mixer.music.load(local_path)
                    pygame.mixer.music.set_volume(self.volume)
                    pygame.mixer.music.play()
                    self.playing = True
                    self.paused = False
                    if self.progress_callback:
                        self.progress_callback(0, f"正在播放 {music_name}")
                    while pygame.mixer.music.get_busy():
                        time.sleep(0.1)
                except Exception as e:
                    pass
        
                    logging.error(f"播放音乐出错: {str(e)}")
                finally:
                    self.playing = False
                return
        logging.error("播放音乐 - 音乐不存在！")

    def start_play(self, music_name):
        """启动播放线程，先停止当前播放"""
        if self.playing:
            self.stop_play()  # 停止当前播放
        self.play_thread = Thread(target=self.play_music, args=(music_name,))
        self.play_thread.start()

    def stop_play(self):
        """停止播放"""
        if self.playing:
            pygame.mixer.music.stop()
            self.playing = False
            self.paused = False

    def pause_play(self):
        """暂停播放"""
        if self.playing and not self.paused:
            pygame.mixer.music.pause()
            self.paused = True

    def unpause_play(self):
        """继续播放"""
        if self.playing and self.paused:
            pygame.mixer.music.unpause()
            self.paused = False

    def set_volume(self, volume):
        """设置音量"""
        self.volume = float(volume)
        if self.playing:
            pygame.mixer.music.set_volume(self.volume)

    def download_music(self, url, music_name):
        """下载音乐并显示进度"""
        local_filename = f"{music_name}.mp3"
        local_path = os.path.join(self.local_dir, local_filename)
        
        # 如果文件已存在，直接返回
        if os.path.exists(local_path):
            if self.progress_callback:
                self.progress_callback(100, f"已下载: {music_name}")
            return True
        
        try:
            # 发送请求获取文件流
            response = requests.get(url, stream=True, verify=False)
            total_size = int(response.headers.get('content-length', 0))
            block_size = 1024  # 1KB 块
            downloaded = 0
            last_update_time = 0
            update_interval = 0.2  # 0.2秒更新一次
            
            with open(local_path, 'wb') as f:
                for data in response.iter_content(block_size):
                    # 检查是否取消下载
                    if getattr(self, 'app', None) and self.app.download_cancelled:
                        self.app.after(0, self.app.restore_download_ui)
                        # 删除不完整文件
                        if os.path.exists(local_path):
                            os.remove(local_path)
                        return
                    downloaded += len(data)
                    f.write(data)
                    # 控制更新频率
                    current_time = time.time()
                    if total_size > 0 and (current_time - last_update_time >= update_interval):
                        progress = (downloaded / total_size) * 100
                        if self.progress_callback:
                            self.progress_callback(progress, f"下载中 {music_name}: {int(progress)}%")
                        last_update_time = current_time
            
            # 下载完成后清理旧文件
            self.clean_old_files()
            # 恢复UI状态
            if getattr(self, 'app', None):
                self.app.after(0, self.app.restore_download_ui)
            
            # 通知下载完成
            if self.progress_callback:
                self.progress_callback(100, f"下载完成: {music_name}")
            return True
        except Exception as e:
    
            # 下载失败时删除不完整文件
            if os.path.exists(local_path):
                os.remove(local_path)
            if self.progress_callback:
                self.progress_callback(0, f"下载失败: {music_name}")
            # 恢复UI状态
            if getattr(self, 'app', None):
                self.app.after(0, self.app.restore_download_ui)
            return False

    def clean_old_files(self):
        """保留最近的3首下载歌曲，删除旧文件"""
        # 获取本地目录所有文件并按修改时间排序
        files = [
            os.path.join(self.local_dir, f) 
            for f in os.listdir(self.local_dir) 
            if os.path.isfile(os.path.join(self.local_dir, f))
        ]
        # 按修改时间升序排序（最旧的在前）
        files.sort(key=lambda x: os.path.getmtime(x))
        
        # 如果文件数超过3个，删除最旧的
        if len(files) > 3:
            for file_to_delete in files[:-3]:
                try:
                    os.remove(file_to_delete)
                    logging.info(f"已删除旧文件: {file_to_delete}")
                except Exception as e:
                    pass
            

class MusicApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.root = self
        self.root.title("音乐播放器")
        self.music_main = Music_main(progress_callback=self.update_progress)
        self.music_main.app = self
        self.downloading = False
        self.download_cancelled = False
        self.current_music_length = 0

        # 设置窗口大小和位置
        self.root.geometry("900x600")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 音乐列表框
        self.music_listbox = tk.Listbox(self.root, width=80, height=15)
        # 创建主框架用于左右布局
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 左侧音乐列表区域
        left_frame = tk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
       # 音乐列表框
        self.music_listbox = tk.Listbox(left_frame, width=40, height=15)
        self.music_listbox.pack(pady=10, fill=tk.BOTH, expand=True)
        
        # 总乐曲数显示
        self.song_count_label = tk.Label(left_frame, text="总乐曲数: 0")
        self.song_count_label.pack(anchor=tk.W, padx=5)

        # 加载音乐列表按钮
        self.load_button = tk.Button(self.root, text="加载音乐列表", command=self.load_music_list)
        self.load_button.pack(pady=5, in_=left_frame)

        # 播放控制按钮框架
        control_frame = tk.Frame(left_frame)
        control_frame.pack(pady=10, in_=left_frame)

        self.play_button = tk.Button(control_frame, text="播放", command=self.play_selected_music, state=tk.DISABLED)
        self.play_button.grid(row=0, column=0, padx=5)

        self.download_button = tk.Button(control_frame, text="下载", command=self.download_selected_music, state=tk.DISABLED)
        self.download_button.grid(row=0, column=1, padx=5)

        self.pause_button = tk.Button(control_frame, text="暂停", command=self.pause_play, state=tk.DISABLED)
        self.pause_button.grid(row=0, column=2, padx=5)
        self.resume_button = tk.Button(control_frame, text="继续", command=self.resume_play, state=tk.DISABLED)
        self.resume_button.grid(row=0, column=3, padx=5)

        # 音量控制
        volume_frame = tk.Frame(left_frame)
        volume_frame.pack(pady=10, in_=left_frame)

        tk.Label(volume_frame, text="音量:").grid(row=0, column=0)
        self.volume_slider = ttk.Scale(
            volume_frame,
            from_=0,
            to=1,
            value=self.music_main.volume,
            command=lambda v: self.set_volume(v)
        )
        self.volume_slider.grid(row=0, column=1, padx=10)
        self.volume_label = tk.Label(volume_frame, text=f"{int(self.music_main.volume*100)}%")
        self.volume_label.grid(row=0, column=2, padx=5)

        # 播放进度显示
        self.play_progress_frame = tk.Frame(left_frame)
        self.play_progress_frame.pack(pady=5, in_=left_frame)
        
        self.play_progress_label = tk.Label(self.play_progress_frame, text="播放进度:")
        self.play_progress_label.grid(row=0, column=0, padx=5)
        
        self.play_progress_bar = ttk.Progressbar(self.play_progress_frame, orient="horizontal", length=300, mode="determinate")
        self.play_progress_bar.grid(row=0, column=1, padx=5)

        # 下载进度显示
        self.progress_frame = tk.Frame(left_frame)
        self.progress_frame.pack(pady=5, in_=left_frame)
        
        self.progress_label = tk.Label(self.progress_frame, text="下载进度:")
        self.progress_label.grid(row=0, column=0, padx=5)
        
        self.progress_bar = ttk.Progressbar(self.progress_frame, orient="horizontal", length=200, mode="determinate")
        self.progress_bar.grid(row=0, column=1, padx=5)
        
        self.cancel_button = tk.Button(self.progress_frame, text="终止下载", command=self.cancel_download, state=tk.DISABLED)
        self.cancel_button.grid(row=0, column=2, padx=5)
        
        self.status_label = tk.Label(left_frame, text="", fg="blue")
        self.status_label.pack(pady=5, in_=left_frame)
        
        # 已移除日志输出组件
        #right_frame = tk.Frame(main_frame)
        #right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        #tk.Label(right_frame, text="日志输出", font=('SimHei', 10, 'bold')).pack(pady=5)
        
        ## 创建滚动条
        #scrollbar = tk.Scrollbar(right_frame)
        #scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        ## 创建文本框用于显示日志输出
        #self.terminal_output = tk.Text(right_frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, bg='black', fg='white', font=('SimHei', 9))
        #self.terminal_output.pack(fill=tk.BOTH, expand=True)
        #scrollbar.config(command=self.terminal_output.yview
        
        # 重定向stdout到文本框
        class TextRedirector:
            def __init__(self, text_widget):
                self.text_widget = text_widget
            def write(self, str):
                self.text_widget.insert(tk.END, str)
                self.text_widget.see(tk.END)  # 滚动到最后
            def flush(self):
                pass
        
        import sys
        #sys.stdout = TextRedirector(self.terminal_output)
        sys.stdout = sys.__stdout__

    def load_music_list(self):
        """加载音乐列表"""
        self.music_listbox.delete(0, tk.END)
        music_list = self.music_main.get_music_list()
        for music in music_list:
            self.music_listbox.insert(tk.END, f"{music['name']} - {music['time_big']}")
        # 更新总乐曲数
        self.song_count_label.config(text=f"总乐曲数: {len(music_list)}")
        # 绑定列表选择事件
        self.music_listbox.bind('<<ListboxSelect>>', self.on_select)

    def set_volume(self, volume):
        self.music_main.set_volume(volume)
        self.volume_label.config(text=f"{int(float(volume)*100)}%")

    def pause_play(self):
        """暂停播放"""
        self.music_main.pause_play()
        self.play_button.config(state=tk.DISABLED)
        self.pause_button.config(state=tk.DISABLED)
        self.resume_button.config(state=tk.NORMAL)

    def resume_play(self):
        """继续播放"""
        self.music_main.unpause_play()
        self.play_button.config(state=tk.DISABLED)
        self.pause_button.config(state=tk.NORMAL)
        self.resume_button.config(state=tk.DISABLED)

    def on_select(self, event):
        if self.downloading:
            return
        selected_index = self.music_listbox.curselection()
        if selected_index:
            selected_text = self.music_listbox.get(selected_index[0])
            music_name = selected_text.split(" - ")[0]
            local_path = os.path.join(self.music_main.local_dir, f"{music_name}.mp3")
            if os.path.exists(local_path):
                self.play_button.config(state=tk.NORMAL)
                self.download_button.config(state=tk.DISABLED)
            else:
                self.play_button.config(state=tk.DISABLED)
                self.download_button.config(state=tk.NORMAL)
        else:
            self.play_button.config(state=tk.DISABLED)
            self.download_button.config(state=tk.DISABLED)

    def download_selected_music(self):
        selected_index = self.music_listbox.curselection()
        if selected_index and not self.downloading:
            selected_text = self.music_listbox.get(selected_index[0])
            music_name = selected_text.split(" - ")[0]
            self.downloading = True
            self.download_cancelled = False
            self.music_listbox.config(state=tk.DISABLED)
            self.download_button.config(state=tk.DISABLED)
            self.cancel_button.config(state=tk.NORMAL)
            self.play_button.config(state=tk.DISABLED)
            
            # 查找音乐URL
            music_url = None
            for music in self.music_main.music_list:
                if music['name'] == music_name:
                    music_url = music['path'].replace("./", "https://huluobuo.github.io/music/")
                    break
            
            if music_url:
                Thread(target=self.music_main.download_music, args=(music_url, music_name), daemon=True).start()

    def cancel_download(self):
        self.download_cancelled = True
        self.status_label.config(text="正在取消下载...")

    def restore_download_ui(self):
        self.downloading = False
        self.music_listbox.config(state=tk.NORMAL)
        self.cancel_button.config(state=tk.DISABLED)
        self.status_label.config(text="下载已取消")
        # 恢复按钮状态
        self.on_select(None)

    def play_selected_music(self):
        """播放选中的音乐"""
        selected_index = self.music_listbox.curselection()
        if selected_index:
            selected_text = self.music_listbox.get(selected_index[0])
            music_name = selected_text.split(" - ")[0]
            local_path = os.path.join(self.music_main.local_dir, f"{music_name}.mp3")
            
            # 获取音乐长度
            try:
                audio = MP3(local_path)
                self.current_music_length = audio.info.length
            except:
                self.current_music_length = 0
            # 重置播放进度条
            self.play_progress_bar['value'] = 0
            
            self.music_main.start_play(music_name)
            self.play_button.config(state=tk.DISABLED)
            self.pause_button.config(state=tk.NORMAL)
            self.resume_button.config(state=tk.DISABLED)
            # 启动播放进度更新
            self.update_play_progress()

    def update_play_progress(self):
        if self.music_main.playing and not self.music_main.paused and self.current_music_length > 0:
            current_pos = pygame.mixer.music.get_pos() / 1000  # 转换为秒
            progress = (current_pos / self.current_music_length) * 100
            self.play_progress_bar['value'] = progress
        # 继续更新进度
        self.after(1000, self.update_play_progress)

    def update_progress(self, progress, status):
        """更新下载进度条和状态标签"""
        self.progress_bar['value'] = progress
        self.status_label.config(text=status)
        self.update_idletasks()  # 强制更新UI
        
        # 从状态中提取音乐名称
        if "下载中" in status:
            music_name = status.split(" ")[1]
            percent = int(status.split(": ")[-1].replace("%", ""))
            # 创建进度条 (20个字符宽)
            bar_length = 20
            filled_length = int(bar_length * percent // 100)
            bar = "█" * filled_length + "-" * (bar_length - filled_length)
            # 使用\r回到行首覆盖输出

        elif "下载完成" in status:
            music_name = status.split(": ")[-1]
            # 下载完成时输出完整信息并换行



    def on_closing(self):
        """窗口关闭时停止播放音乐"""
        self.music_main.stop_play()
        self.root.destroy()

if __name__ == "__main__":
    
    app = MusicApp()
    app.mainloop()