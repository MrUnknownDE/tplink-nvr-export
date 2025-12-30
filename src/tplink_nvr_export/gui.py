"""
TP-Link Vigi NVR Export - GUI Application

A simple tkinter-based GUI for exporting video recordings from TP-Link Vigi NVRs.
"""

import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .auth import AuthenticationError
from .nvr_client import NVRAPIError, NVRClient


class NVRExportGUI:
    """Main GUI application for NVR video export."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TP-Link Vigi NVR Export")
        self.root.geometry("550x650")
        self.root.resizable(True, True)
        
        # Set minimum size
        self.root.minsize(500, 600)
        
        # Configure style
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Variables
        self.host_var = tk.StringVar(value="192.168.1.100")
        self.port_var = tk.StringVar(value="20443")
        self.user_var = tk.StringVar(value="admin")
        self.password_var = tk.StringVar()
        self.channel_var = tk.StringVar(value="1")
        self.output_var = tk.StringVar(value=str(Path.home() / "Downloads" / "nvr-exports"))
        self.type_var = tk.StringVar(value="all")
        
        # Date/time variables - default to last 24 hours
        now = datetime.now()
        yesterday = now - timedelta(days=1)
        self.start_date_var = tk.StringVar(value=yesterday.strftime("%Y-%m-%d"))
        self.start_time_var = tk.StringVar(value="00:00")
        self.end_date_var = tk.StringVar(value=now.strftime("%Y-%m-%d"))
        self.end_time_var = tk.StringVar(value="23:59")
        
        # State
        self.client: Optional[NVRClient] = None
        self.is_exporting = False
        
        self._create_widgets()
        self._configure_grid()
    
    def _create_widgets(self):
        """Create all GUI widgets."""
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        row = 0
        
        # Title
        title_label = ttk.Label(
            main_frame, 
            text="🎥 TP-Link Vigi NVR Export",
            font=("Segoe UI", 16, "bold")
        )
        title_label.grid(row=row, column=0, columnspan=3, pady=(0, 15))
        row += 1
        
        # === Connection Section ===
        conn_frame = ttk.LabelFrame(main_frame, text="🔗 NVR Connection", padding="10")
        conn_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        conn_frame.columnconfigure(1, weight=1)
        row += 1
        
        # Host
        ttk.Label(conn_frame, text="Host:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(conn_frame, textvariable=self.host_var, width=30).grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        
        # Port
        ttk.Label(conn_frame, text="Port:").grid(row=0, column=2, sticky="w", padx=(10, 0), pady=2)
        ttk.Entry(conn_frame, textvariable=self.port_var, width=8).grid(row=0, column=3, sticky="w", pady=2)
        
        # Username
        ttk.Label(conn_frame, text="User:").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(conn_frame, textvariable=self.user_var).grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        
        # Password
        ttk.Label(conn_frame, text="Password:").grid(row=1, column=2, sticky="w", padx=(10, 0), pady=2)
        ttk.Entry(conn_frame, textvariable=self.password_var, show="*").grid(row=1, column=3, sticky="ew", pady=2)
        
        # Test connection button
        self.test_btn = ttk.Button(conn_frame, text="🔌 Test Connection", command=self._test_connection)
        self.test_btn.grid(row=2, column=0, columnspan=4, pady=(10, 0))
        
        # === Time Range Section ===
        time_frame = ttk.LabelFrame(main_frame, text="📅 Time Range", padding="10")
        time_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        row += 1
        
        # Start date/time
        ttk.Label(time_frame, text="Start:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(time_frame, textvariable=self.start_date_var, width=12).grid(row=0, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(time_frame, text="YYYY-MM-DD").grid(row=0, column=2, sticky="w")
        ttk.Entry(time_frame, textvariable=self.start_time_var, width=8).grid(row=0, column=3, sticky="w", padx=5, pady=2)
        ttk.Label(time_frame, text="HH:MM").grid(row=0, column=4, sticky="w")
        
        # End date/time
        ttk.Label(time_frame, text="End:").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(time_frame, textvariable=self.end_date_var, width=12).grid(row=1, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(time_frame, text="YYYY-MM-DD").grid(row=1, column=2, sticky="w")
        ttk.Entry(time_frame, textvariable=self.end_time_var, width=8).grid(row=1, column=3, sticky="w", padx=5, pady=2)
        ttk.Label(time_frame, text="HH:MM").grid(row=1, column=4, sticky="w")
        
        # Quick select buttons
        quick_frame = ttk.Frame(time_frame)
        quick_frame.grid(row=2, column=0, columnspan=5, pady=(10, 0))
        ttk.Button(quick_frame, text="Last 24h", command=lambda: self._set_quick_range(1)).pack(side="left", padx=2)
        ttk.Button(quick_frame, text="Last 7 Days", command=lambda: self._set_quick_range(7)).pack(side="left", padx=2)
        ttk.Button(quick_frame, text="Last 30 Days", command=lambda: self._set_quick_range(30)).pack(side="left", padx=2)
        
        # === Export Settings Section ===
        export_frame = ttk.LabelFrame(main_frame, text="⚙️ Export Settings", padding="10")
        export_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        export_frame.columnconfigure(1, weight=1)
        row += 1
        
        # Channel
        ttk.Label(export_frame, text="Channel:").grid(row=0, column=0, sticky="w", pady=2)
        channel_spin = ttk.Spinbox(export_frame, from_=1, to=32, textvariable=self.channel_var, width=5)
        channel_spin.grid(row=0, column=1, sticky="w", padx=5, pady=2)
        
        # Recording type
        ttk.Label(export_frame, text="Type:").grid(row=0, column=2, sticky="w", padx=(20, 0), pady=2)
        type_combo = ttk.Combobox(
            export_frame, 
            textvariable=self.type_var,
            values=["all", "continuous", "motion", "alarm"],
            state="readonly",
            width=12
        )
        type_combo.grid(row=0, column=3, sticky="w", pady=2)
        
        # Output directory
        ttk.Label(export_frame, text="Output:").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(export_frame, textvariable=self.output_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=5, pady=2)
        ttk.Button(export_frame, text="📁 Browse", command=self._browse_output).grid(row=1, column=3, sticky="w", pady=2)
        
        # === Progress Section ===
        progress_frame = ttk.LabelFrame(main_frame, text="📊 Progress", padding="10")
        progress_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)
        row += 1
        
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame, 
            variable=self.progress_var,
            maximum=100,
            mode='determinate'
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", pady=5)
        
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(progress_frame, textvariable=self.status_var)
        self.status_label.grid(row=1, column=0, sticky="w")
        
        # === Action Buttons ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=15)
        row += 1
        
        self.search_btn = ttk.Button(btn_frame, text="🔍 Search Recordings", command=self._search_recordings)
        self.search_btn.pack(side="left", padx=5)
        
        self.export_btn = ttk.Button(btn_frame, text="📥 Export", command=self._start_export)
        self.export_btn.pack(side="left", padx=5)
        
        self.cancel_btn = ttk.Button(btn_frame, text="❌ Cancel", command=self._cancel_export, state="disabled")
        self.cancel_btn.pack(side="left", padx=5)
        
        # === Log Section ===
        log_frame = ttk.LabelFrame(main_frame, text="📝 Log", padding="10")
        log_frame.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(row, weight=1)
        row += 1
        
        self.log_text = tk.Text(log_frame, height=8, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        self._log("Ready. Configure NVR connection and click 'Test Connection' to start.")
    
    def _configure_grid(self):
        """Configure grid weights for resizing."""
        pass  # Already configured in _create_widgets
    
    def _log(self, message: str):
        """Add message to log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
    
    def _set_quick_range(self, days: int):
        """Set quick time range."""
        now = datetime.now()
        start = now - timedelta(days=days)
        self.start_date_var.set(start.strftime("%Y-%m-%d"))
        self.start_time_var.set("00:00")
        self.end_date_var.set(now.strftime("%Y-%m-%d"))
        self.end_time_var.set("23:59")
    
    def _browse_output(self):
        """Open folder browser for output directory."""
        folder = filedialog.askdirectory(initialdir=self.output_var.get())
        if folder:
            self.output_var.set(folder)
    
    def _get_client(self) -> NVRClient:
        """Get or create NVR client."""
        return NVRClient(
            host=self.host_var.get(),
            username=self.user_var.get(),
            password=self.password_var.get(),
            port=int(self.port_var.get()),
            verify_ssl=False,
        )
    
    def _parse_datetime(self, date_str: str, time_str: str) -> datetime:
        """Parse date and time strings."""
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    
    def _test_connection(self):
        """Test connection to NVR."""
        self.status_var.set("Testing connection...")
        self._log(f"Connecting to {self.host_var.get()}:{self.port_var.get()}...")
        
        def test():
            try:
                with self._get_client() as client:
                    channels = client.get_channels()
                    self.root.after(0, lambda: self._on_test_success(channels))
            except (AuthenticationError, NVRAPIError) as e:
                self.root.after(0, lambda: self._on_test_error(str(e)))
            except Exception as e:
                self.root.after(0, lambda: self._on_test_error(f"Unexpected error: {e}"))
        
        threading.Thread(target=test, daemon=True).start()
    
    def _on_test_success(self, channels):
        """Handle successful connection test."""
        self.status_var.set("Connected!")
        self._log(f"✅ Connection successful! Found {len(channels)} channels.")
        for ch in channels:
            self._log(f"   Channel {ch.id}: {ch.name}")
    
    def _on_test_error(self, error: str):
        """Handle connection test error."""
        self.status_var.set("Connection failed")
        self._log(f"❌ Connection failed: {error}")
        messagebox.showerror("Connection Error", error)
    
    def _search_recordings(self):
        """Search for recordings without downloading."""
        self.status_var.set("Searching...")
        self._log("Searching for recordings...")
        
        def search():
            try:
                start = self._parse_datetime(self.start_date_var.get(), self.start_time_var.get())
                end = self._parse_datetime(self.end_date_var.get(), self.end_time_var.get())
                channel = int(self.channel_var.get())
                
                with self._get_client() as client:
                    recordings = client.search_recordings(channel, start, end, self.type_var.get())
                    self.root.after(0, lambda: self._on_search_success(recordings))
            except Exception as e:
                self.root.after(0, lambda: self._on_search_error(str(e)))
        
        threading.Thread(target=search, daemon=True).start()
    
    def _on_search_success(self, recordings):
        """Handle successful search."""
        if not recordings:
            self.status_var.set("No recordings found")
            self._log("⚠️ No recordings found for the specified time range.")
            return
        
        total_size = sum(r.size_bytes for r in recordings) / (1024 * 1024)
        total_duration = sum(r.duration_seconds for r in recordings)
        hours = total_duration // 3600
        minutes = (total_duration % 3600) // 60
        
        self.status_var.set(f"Found {len(recordings)} recordings")
        self._log(f"✅ Found {len(recordings)} recordings ({total_size:.1f} MB, {hours}h {minutes}m)")
    
    def _on_search_error(self, error: str):
        """Handle search error."""
        self.status_var.set("Search failed")
        self._log(f"❌ Search failed: {error}")
    
    def _start_export(self):
        """Start export process."""
        if self.is_exporting:
            return
        
        self.is_exporting = True
        self.export_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress_var.set(0)
        self.status_var.set("Exporting...")
        self._log("Starting export...")
        
        def export():
            try:
                start = self._parse_datetime(self.start_date_var.get(), self.start_time_var.get())
                end = self._parse_datetime(self.end_date_var.get(), self.end_time_var.get())
                channel = int(self.channel_var.get())
                output_dir = Path(self.output_var.get())
                
                with self._get_client() as client:
                    recordings = client.search_recordings(channel, start, end, self.type_var.get())
                    
                    if not recordings:
                        self.root.after(0, lambda: self._log("⚠️ No recordings found."))
                        return
                    
                    self.root.after(0, lambda: self._log(f"Downloading {len(recordings)} recordings..."))
                    
                    for i, rec in enumerate(recordings):
                        if not self.is_exporting:
                            break
                        
                        progress = ((i + 1) / len(recordings)) * 100
                        self.root.after(0, lambda p=progress: self.progress_var.set(p))
                        self.root.after(0, lambda r=rec: self.status_var.set(f"Downloading: {r.start_time:%H:%M}"))
                        
                        try:
                            output_file = client.download_recording(rec, output_dir)
                            self.root.after(0, lambda f=output_file: self._log(f"✅ Downloaded: {f.name}"))
                        except NVRAPIError as e:
                            self.root.after(0, lambda e=e: self._log(f"⚠️ Failed: {e}"))
                    
                    self.root.after(0, self._on_export_complete)
                    
            except Exception as e:
                self.root.after(0, lambda: self._on_export_error(str(e)))
        
        threading.Thread(target=export, daemon=True).start()
    
    def _on_export_complete(self):
        """Handle export completion."""
        self.is_exporting = False
        self.export_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.progress_var.set(100)
        self.status_var.set("Export complete!")
        self._log("🎉 Export completed!")
        messagebox.showinfo("Export Complete", f"Recordings exported to:\n{self.output_var.get()}")
    
    def _on_export_error(self, error: str):
        """Handle export error."""
        self.is_exporting = False
        self.export_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.status_var.set("Export failed")
        self._log(f"❌ Export failed: {error}")
        messagebox.showerror("Export Error", error)
    
    def _cancel_export(self):
        """Cancel ongoing export."""
        self.is_exporting = False
        self.status_var.set("Cancelled")
        self._log("⚠️ Export cancelled by user.")
    
    def run(self):
        """Start the GUI application."""
        self.root.mainloop()


def main():
    """Entry point for GUI application."""
    app = NVRExportGUI()
    app.run()


if __name__ == "__main__":
    main()
