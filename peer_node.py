import socket
import threading
import json
import time
import sys
import tkinter as tk
from tkinter import scrolledtext, messagebox
import queue

BOOTSTRAP_IP = '127.0.0.1'
BOOTSTRAP_PORT = 5000

class Peer:
    def __init__(self, port, ui_queue):
        self.ip = '127.0.0.1'
        self.port = port
        self.known_peers = []
        self.lock = threading.Lock()
        self.ui_queue = ui_queue

    def start_server(self):
        """Vai trò Server: Lắng nghe tin nhắn đến đồng thời với việc gửi đi"""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(('0.0.0.0', self.port))
        server.listen(5)
        while True:
            conn, addr = server.accept()
            threading.Thread(target=self.handle_incoming, args=(conn, addr)).start()

    def handle_incoming(self, conn, addr):
        try:
            data = conn.recv(1024).decode('utf-8')
            if data:
                msg = json.loads(data)
                if msg['type'] == 'CHAT':
                    self.ui_queue.put(('chat', f"[Tin nhắn 1-1 từ {msg['sender']}]: {msg['content']}"))
                elif msg['type'] == 'GROUP_CHAT':
                    self.ui_queue.put(('chat', f"[Nhóm '{msg['group']}' - từ {msg['sender']}]: {msg['content']}"))
        except Exception as e:
            pass
        finally:
            conn.close()

    def heartbeat_loop(self):
        """Yêu cầu 3.4 & 3.5: Cơ chế Peer Discovery và Cập nhật trạng thái liên tục"""
        while True:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                s.connect((BOOTSTRAP_IP, BOOTSTRAP_PORT))
                s.send(json.dumps({'type': 'HEARTBEAT', 'port': self.port}).encode('utf-8'))
                
                response = s.recv(4096).decode('utf-8')
                if response:
                    msg = json.loads(response)
                    if msg.get('type') == 'PEER_LIST':
                        with self.lock:
                            self.known_peers = [(p['ip'], p['port']) for p in msg['peers'] if p['port'] != self.port]
                        self.ui_queue.put(('peers', self.known_peers))
            except Exception as e:
                pass
            finally:
                s.close()
            time.sleep(5)  # Gửi heartbeat (nhịp tim) mỗi 5 giây

    def send_message(self, target_ip, target_port, content, msg_type='CHAT', group_name=None):
        """Yêu cầu 3.6: Truyền tin đáng tin cậy. Bắt lỗi khi peer đích mất kết nối"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((target_ip, target_port))
            
            payload = {
                'type': msg_type,
                'sender': f"{self.ip}:{self.port}",
                'content': content
            }
            if group_name:
                payload['group'] = group_name
                
            s.send(json.dumps(payload).encode('utf-8'))
            s.close()
            return True
        except socket.error:
            self.ui_queue.put(('chat', f"[!] Giao tiếp thất bại với {target_ip}:{target_port}."))
            return False

    def start_threads(self):
        threading.Thread(target=self.start_server, daemon=True).start()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        self.ui_queue.put(('chat', f"[*] Peer khởi chạy thành công tại {self.ip}:{self.port}"))

class ChatGUI:
    def __init__(self, root, port):
        self.root = root
        self.root.title(f"P2P Chat Node - Port {port}")
        self.root.geometry("600x450")
        
        self.ui_queue = queue.Queue()
        self.peer = Peer(port, self.ui_queue)
        
        self.setup_ui()
        self.peer.start_threads()
        self.process_queue()

    def setup_ui(self):
        # Khung chat bên trái
        left_frame = tk.Frame(self.root)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.chat_display = scrolledtext.ScrolledText(left_frame, state='disabled', height=15)
        self.chat_display.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Khung nhập tin nhắn
        msg_frame = tk.Frame(left_frame)
        msg_frame.pack(fill=tk.X, pady=2)
        tk.Label(msg_frame, text="Tin nhắn:").pack(side=tk.LEFT)
        self.msg_entry = tk.Entry(msg_frame)
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Khung gửi 1-1
        direct_frame = tk.Frame(left_frame)
        direct_frame.pack(fill=tk.X, pady=2)
        tk.Label(direct_frame, text="IP:").pack(side=tk.LEFT)
        self.ip_entry = tk.Entry(direct_frame, width=12)
        self.ip_entry.insert(0, "127.0.0.1")
        self.ip_entry.pack(side=tk.LEFT, padx=5)
        tk.Label(direct_frame, text="Port:").pack(side=tk.LEFT)
        self.port_entry = tk.Entry(direct_frame, width=6)
        self.port_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(direct_frame, text="Gửi 1-1", command=self.send_direct).pack(side=tk.LEFT, padx=5)
        
        # Khung gửi Nhóm
        group_frame = tk.Frame(left_frame)
        group_frame.pack(fill=tk.X, pady=2)
        tk.Label(group_frame, text="Tên nhóm:").pack(side=tk.LEFT)
        self.group_entry = tk.Entry(group_frame, width=12)
        self.group_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(group_frame, text="Gửi Nhóm", command=self.send_group).pack(side=tk.LEFT, padx=5)

        # Khung danh sách Peer bên phải
        right_frame = tk.Frame(self.root)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        tk.Label(right_frame, text="Peers Online").pack()
        self.peer_list = tk.Listbox(right_frame, width=20)
        self.peer_list.pack(fill=tk.Y, expand=True)

    def process_queue(self):
        """Hàm cập nhật giao diện định kỳ mà không block luồng xử lý chính"""
        try:
            while True:
                msg_type, data = self.ui_queue.get_nowait()
                if msg_type == 'chat':
                    self.chat_display.config(state='normal')
                    self.chat_display.insert(tk.END, data + "\n")
                    self.chat_display.config(state='disabled')
                    self.chat_display.yview(tk.END)
                elif msg_type == 'peers':
                    self.peer_list.delete(0, tk.END)
                    for p in data:
                        self.peer_list.insert(tk.END, f"{p[0]}:{p[1]}")
        except queue.Empty:
            pass
        # Cứ 100ms kiểm tra hàng đợi một lần
        self.root.after(100, self.process_queue)

    def send_direct(self):
        ip = self.ip_entry.get()
        port_str = self.port_entry.get()
        msg = self.msg_entry.get()
        if not ip or not port_str or not msg:
            messagebox.showwarning("Lỗi", "Vui lòng nhập IP, Port và Tin nhắn!")
            return
        port = int(port_str)
        self.chat_display.config(state='normal')
        self.chat_display.insert(tk.END, f"[Bạn -> {ip}:{port}]: {msg}\n")
        self.chat_display.config(state='disabled')
        self.chat_display.yview(tk.END)
        self.peer.send_message(ip, port, msg)
        self.msg_entry.delete(0, tk.END)

    def send_group(self):
        grp = self.group_entry.get()
        msg = self.msg_entry.get()
        if not grp or not msg:
            messagebox.showwarning("Lỗi", "Vui lòng nhập Tên nhóm và Tin nhắn!")
            return
        self.chat_display.config(state='normal')
        self.chat_display.insert(tk.END, f"[Bạn -> Nhóm '{grp}']: {msg}\n")
        self.chat_display.config(state='disabled')
        self.chat_display.yview(tk.END)
        
        with self.peer.lock:
            peers = self.peer.known_peers.copy()
        for peer_ip, peer_port in peers:
            self.peer.send_message(peer_ip, peer_port, msg, msg_type='GROUP_CHAT', group_name=grp)
        self.msg_entry.delete(0, tk.END)

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 6001
    root = tk.Tk()
    app = ChatGUI(root, port)
    root.mainloop()