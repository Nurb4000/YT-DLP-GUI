import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import re

# --- Configuration ---
CONDA_ENV_NAME = "ytdlp"
CONDA_EXE = "conda" if sys.platform != "win32" else "conda.exe"

def get_conda_exe():
    result = subprocess.run(
        ["which", CONDA_EXE] if sys.platform != "win32" else ["where", CONDA_EXE],
        capture_output=True, text=True, check=False
    )
    conda_path = result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
    if conda_path and os.path.exists(conda_path):
        return conda_path
    for p in [
        os.path.join(os.path.expanduser("~"), "miniconda3", "bin", "conda"),
        os.path.join(os.path.expanduser("~"), "anaconda3", "bin", "conda"),
    ]:
        if os.path.exists(p):
            return p
    return CONDA_EXE

CONDA_EXE = get_conda_exe()

def ensure_conda_env():
    result = subprocess.run(
        [CONDA_EXE, "info", "--envs"],
        capture_output=True,
        text=True
    )
    if CONDA_ENV_NAME not in result.stdout:
        print(f"Creating Conda environment '{CONDA_ENV_NAME}'...")
        subprocess.run(
            [CONDA_EXE, "create", "-y", "-n", CONDA_ENV_NAME, "python=3.11", "pip"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"✅ Environment '{CONDA_ENV_NAME}' created with pip.")
    else:
        print(f"✅ Conda env '{CONDA_ENV_NAME}' exists.")

def get_conda_python():
    base_env_result = subprocess.run(
        [CONDA_EXE, "info", "--base"],
        capture_output=True,
        text=True,
        check=True
    )
    base_env = base_env_result.stdout.strip()

    if sys.platform == "win32":
        python_path = os.path.join(base_env, "envs", CONDA_ENV_NAME, "python.exe")
    else:
        python_path = os.path.join(base_env, "envs", CONDA_ENV_NAME, "bin", "python")

    if not os.path.exists(python_path):
        raise FileNotFoundError(f"Python not found at '{python_path}'.")
    return python_path

def ensure_pip_in_env():
    python = get_conda_python()
    try:
        subprocess.run(
            [python, "-c", "import pip; print('pip OK')"],
            check=True,
            capture_output=True,
            text=True
        )
        return
    except subprocess.CalledProcessError:
        print("pip missing — installing via ensurepip...")

    try:
        subprocess.run(
            [python, "-m", "ensurepip", "--upgrade"],
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ pip installed via ensurepip.")
    except Exception:
        import urllib.request
        url = "https://bootstrap.pypa.io/get-pip.py"
        get_pip = "get-pip.py"
        urllib.request.urlretrieve(url, get_pip)
        subprocess.run([python, get_pip], check=True, stdout=subprocess.DEVNULL)
        os.remove(get_pip)
        print("✅ pip installed via get-pip.py fallback.")

def upgrade_yt_dlp():
    ensure_conda_env()
    ensure_pip_in_env()
    python = get_conda_python()
    print(f"Upgrading yt-dlp using: {python}")
    try:
        subprocess.run(
            [python, "-m", "pip", "install", "--upgrade", "yt-dlp"],
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ yt-dlp upgraded successfully.")
    except subprocess.CalledProcessError as e:
        error = e.stderr or e.stdout or str(e)
        messagebox.showwarning("Upgrade Warning", f"Could not auto-upgrade yt-dlp:\n{error}")
        print(f"⚠️ Warning: {error}")

# 🔑 ROBUST FILESIZE: Fixed parsing for ~ prefixed strings and raw numeric approximations
def get_filesize(fmt):
    # Helper to convert bytes to human readable
    def bytes_to_human(num_bytes, is_approx=False):
        if num_bytes <= 0:
            return None
        prefix = "~ " if is_approx else ""
        
        if num_bytes >= 1024**3:
            return f"{prefix}{num_bytes / (1024**3):.2f}GiB"
        elif num_bytes >= 1024**2:
            return f"{prefix}{num_bytes / (1024**2):.2f}MiB"
        elif num_bytes >= 1024:
            return f"{prefix}{num_bytes / 1024:.2f}KiB"
        else:
            return f"{prefix}{num_bytes} B"

    # 1. Check filesize_approx (This is often where the ~ string comes from)
    approx_val = fmt.get("filesize_approx")
    
    if approx_val is not None:
        # Case A: It's a string like "~ 42.85MiB" or "42.85MiB"
        if isinstance(approx_val, str):
            clean_str = approx_val.strip().lstrip("~").strip()
            # Regex to find number and optional unit
            match = re.search(r'([\d.]+)\s*(GiB|MiB|KiB|GB|MB|KB|B)?', clean_str, re.IGNORECASE)
            if match:
                try:
                    num = float(match.group(1))
                    unit = (match.group(2) or "B").upper()
                    
                    # Convert to bytes
                    bytes_val = num
                    if unit == "GB":
                        bytes_val *= 1024**3
                    elif unit == "MB":
                        bytes_val *= 1024**2
                    elif unit == "KB":
                        bytes_val *= 1024
                    elif unit == "GIB":
                        bytes_val *= 1024**3
                    elif unit == "MIB":
                        bytes_val *= 1024**2
                    elif unit == "KIB":
                        bytes_val *= 1024
                    
                    return bytes_to_human(bytes_val, is_approx=True)
                except ValueError:
                    pass # Fall through to next check
        
        # Case B: It's a raw number (bytes)
        elif isinstance(approx_val, (int, float)):
            return bytes_to_human(approx_val, is_approx=True)

    # 2. Check standard filesize (exact)
    exact_size = fmt.get("filesize")
    if exact_size is not None and isinstance(exact_size, (int, float)):
        return bytes_to_human(exact_size, is_approx=False)

    return "N/A"

def fetch_formats_json(url, python):
    try:
        result = subprocess.run(
            [python, "-m", "yt_dlp",
             "--remote-components", "ejs:github", "-J", "--flat-playlist", url],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        formats = []
        for fmt in data.get("formats", []):
            # Skip non-playable formats
            if fmt.get("vcodec") == "none" and fmt.get("acodec") == "none":
                continue
            
            formats.append({
                "id": str(fmt.get("format_id", "")),
                "ext": fmt.get("ext", ""),
                "resolution": fmt.get("resolution", "audio only"),
                "filesize": get_filesize(fmt),
                "tbr": fmt.get("tbr", 0) or 0,
                "proto": fmt.get("protocol", "unknown"),
                "vcodec": fmt.get("vcodec") or "none",
                "acodec": fmt.get("acodec") or "none",
                "info": fmt.get("format_note", "") or ""
            })
        return formats
    except subprocess.CalledProcessError as e:
        raise Exception(f"yt-dlp error: {e.stderr}")
    except json.JSONDecodeError as e:
        raise Exception(f"JSON parse error: {e}")

class YTDLPDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("yt-dlp Downloader")
        self.root.geometry("1000x700")
        self.python_path = None
        self.create_widgets()
        threading.Thread(target=self._pre_check, daemon=True).start()

    def _pre_check(self):
        try:
            upgrade_yt_dlp()
            self.python_path = get_conda_python()
            self.log(f"✅ Using: {self.python_path}")
        except Exception as e:
            self.log(f"❌ Setup failed: {e}")
            messagebox.showerror("Setup Error", str(e))

    def create_widgets(self):
        # URL Frame
        url_frame = ttk.LabelFrame(self.root, text="Video URL", padding=10)
        url_frame.pack(fill="x", padx=10, pady=5)

        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(url_frame, textvariable=self.url_var, width=80)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.url_entry.focus()
        self.fetch_btn = ttk.Button(url_frame, text="Fetch Formats", command=self.fetch_formats)
        self.fetch_btn.pack(side="left")

        # Status Frame
        log_frame = ttk.LabelFrame(self.root, text="Status", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state="disabled", height=6, wrap="word", font=("Courier", 9))
        self.log_text.pack(fill="both", expand=True)

        # Formats Frame
        fmt_frame = ttk.LabelFrame(self.root, text="Available Formats", padding=5)
        fmt_frame.pack(fill="both", expand=True, padx=10, pady=5)

        columns = ("id", "ext", "resolution", "filesize", "tbr", "proto", "vcodec", "acodec")
        self.format_tree = ttk.Treeview(fmt_frame, columns=columns, show="headings", height=15)
        for col in columns:
            self.format_tree.heading(col, text=col.upper())
            self.format_tree.column(col, width=80, anchor="center")
        
        self.format_tree.column("id", width=60, anchor="center")
        self.format_tree.column("ext", width=60, anchor="center")
        self.format_tree.column("resolution", width=120, anchor="center")
        self.format_tree.column("filesize", width=120, anchor="center")
        self.format_tree.column("tbr", width=80, anchor="center")
        self.format_tree.column("proto", width=80, anchor="center")
        self.format_tree.column("vcodec", width=180, anchor="center")
        self.format_tree.column("acodec", width=180, anchor="center")

        self.format_tree.pack(side="left", fill="both", expand=True)
        tree_scroll = ttk.Scrollbar(fmt_frame, orient="vertical", command=self.format_tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self.format_tree.configure(yscroll=tree_scroll)

        self.format_tree.bind("<<TreeviewSelect>>", self.on_format_select)

        # Download Frame
        download_frame = ttk.Frame(self.root)
        self.download_btn = ttk.Button(download_frame, text="Download Selected", command=self.download_selected)
        self.download_btn.pack(side="left", padx=(0,10))
        self.download_btn.config(state="disabled")
        self.clear_btn = ttk.Button(download_frame, text="Clear", command=self.clear_selection)
        self.clear_btn.pack(side="left")
        download_frame.pack(fill="x", padx=10, pady=5)

    def on_format_select(self, event=None):
        selected = self.format_tree.selection()
        if selected:
            self.download_btn.config(state="normal")
        else:
            self.download_btn.config(state="disabled")

    def log(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, f"[{msg}]\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        self.root.update_idletasks()

    def fetch_formats(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Input Error", "Please enter a URL.")
            return
        if not self.python_path:
            messagebox.showerror("Setup Error", "Environment not ready.")
            return

        self.fetch_btn.config(state="disabled")
        self.log(f"Fetching formats for: {url}")

        def run_fetch():
            try:
                formats = fetch_formats_json(url, self.python_path)
                self.display_formats(formats)
                self.log(f"✅ Found {len(formats)} format(s).")
            except Exception as e:
                self.log(f"❌ Fetch failed: {e}")
                messagebox.showerror("Fetch Error", str(e))
            finally:
                self.fetch_btn.config(state="normal")
                self.download_btn.config(state="disabled")

        threading.Thread(target=run_fetch, daemon=True).start()

    def display_formats(self, formats):
        for item in self.format_tree.get_children():
            self.format_tree.delete(item)
        for fmt in formats:
            self.format_tree.insert("", tk.END, values=(
                fmt["id"], fmt["ext"], fmt["resolution"],
                fmt["filesize"], fmt["tbr"], fmt["proto"],
                fmt["vcodec"], fmt["acodec"]
            ))
        self.download_btn.config(state="disabled")

    def clear_selection(self):
        for item in self.format_tree.selection():
            self.format_tree.selection_remove(item)
        self.download_btn.config(state="disabled")
        self.log("Selection cleared.")

    def download_selected(self):
        selected = self.format_tree.selection()
        if not selected:
            messagebox.showwarning("Selection", "Pick a format first.")
            return
        
        # Ensure the ID is cast to string to avoid TypeError in subprocess
        fmt_id = str(self.format_tree.item(selected[0])["values"][0])
        
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("URL", "Re-enter the video URL.")
            return

        self.download_btn.config(state="disabled")
        self.log(f"Downloading format {fmt_id}: {url}")

        def run_download():
            try:
                result = subprocess.run(
                    [self.python_path, "-m", "yt_dlp",
                     "--remote-components", "ejs:github", "-f", fmt_id, url],
                    check=True, capture_output=True, text=True
                )
                self.log(f"✅ Done! Last 500 chars:\n{result.stdout[-500:]}")
            except subprocess.CalledProcessError as e:
                self.log(f"❌ Download failed: {e.stderr}")
                messagebox.showerror("Download Error", e.stderr or str(e))
            finally:
                self.download_btn.config(state="normal")

        threading.Thread(target=run_download, daemon=True).start()


if __name__ == "__main__":
    print("🚀 Setting up Conda env 'ytdlp' with pip...")
    root = tk.Tk()
    app = YTDLPDownloaderGUI(root)
    root.mainloop()

