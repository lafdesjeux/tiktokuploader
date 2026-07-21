from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from zoneinfo import ZoneInfo

from .api import utf16_length
from .service import PublisherService


class PublisherGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TikTok Desktop Publisher")
        self.geometry("920x720")
        self.minsize(820, 650)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.service = PublisherService(log=self.log)
        self.creator = None
        self._build_style()
        self._build_ui()
        self._load_settings()
        self.after(100, self._drain_events)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("TkDefaultFont", 18, "bold"))
        style.configure("Section.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Accent.TButton", padding=(14, 8))

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text="TikTok Desktop Publisher", style="Title.TLabel").pack(side="left")
        self.connection_status = tk.StringVar(value="Not connected")
        self.connection_label = ttk.Label(header, textvariable=self.connection_status)
        self.connection_label.pack(side="right")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.account_tab = ttk.Frame(self.tabs, padding=18)
        self.publish_tab = ttk.Frame(self.tabs, padding=18)
        self.queue_tab = ttk.Frame(self.tabs, padding=18)
        self.settings_tab = ttk.Frame(self.tabs, padding=18)
        self.log_tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.account_tab, text="1. Account")
        self.tabs.add(self.publish_tab, text="2. Publish")
        self.tabs.add(self.queue_tab, text="3. Local queue")
        self.tabs.add(self.settings_tab, text="Settings")
        self.tabs.add(self.log_tab, text="Logs")
        self._build_account_tab()
        self._build_publish_tab()
        self._build_queue_tab()
        self._build_settings_tab()
        self._build_log_tab()

    def _build_account_tab(self) -> None:
        frame = self.account_tab
        ttk.Label(frame, text="Connect a TikTok creator account", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                "TikTok opens in your browser. Review the requested permissions, choose the account "
                "you want to use, and approve access. The application never asks for your TikTok password."
            ),
            wraplength=760,
        ).pack(anchor="w", pady=(10, 20))
        buttons = ttk.Frame(frame)
        buttons.pack(anchor="w")
        ttk.Button(buttons, text="Connect with TikTok", style="Accent.TButton", command=self.connect).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(buttons, text="Refresh creator info", command=self.refresh_creator).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Disconnect", command=self.disconnect).pack(side="left")
        ttk.Separator(frame).pack(fill="x", pady=24)
        ttk.Label(frame, text="Authorized creator", style="Section.TLabel").pack(anchor="w")
        self.creator_summary = tk.StringVar(value="No creator information loaded.")
        ttk.Label(frame, textvariable=self.creator_summary, wraplength=760).pack(anchor="w", pady=(10, 0))
        ttk.Label(
            frame,
            text=(
                "The privacy list, interaction restrictions, and maximum video duration are loaded "
                "from TikTok and applied to the Publish screen."
            ),
            wraplength=760,
        ).pack(anchor="w", pady=(22, 0))

    def _build_settings_tab(self) -> None:
        frame = self.settings_tab
        ttk.Label(frame, text="Developer configuration", style="Section.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )
        ttk.Label(
            frame,
            text=(
                "This section is configured once by the application operator. Normal creators only use "
                "the Account and Publish tabs. Secrets are stored locally and never committed to GitHub."
            ),
            wraplength=740,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 16))
        self.client_key = tk.StringVar()
        self.client_secret = tk.StringVar()
        self.redirect_uri = tk.StringVar(value="http://127.0.0.1:3455/callback/")
        self.timezone_name = tk.StringVar(value="Europe/Luxembourg")
        rows = [
            ("Client key", self.client_key, False),
            ("Client secret", self.client_secret, True),
            ("Desktop redirect URI", self.redirect_uri, False),
            ("Timezone", self.timezone_name, False),
        ]
        for row, (label, variable, secret) in enumerate(rows, start=2):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=6)
            entry = ttk.Entry(frame, textvariable=variable, show="•" if secret else "")
            entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=6)
        ttk.Button(frame, text="Save developer settings", command=self.save_settings).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(16, 0)
        )
        frame.columnconfigure(1, weight=1)

    def _build_publish_tab(self) -> None:
        frame = self.publish_tab
        self.video_path = tk.StringVar()
        self.privacy = tk.StringVar(value="SELF_ONLY")
        self.publish_at = tk.StringVar()
        self.disable_comment = tk.BooleanVar()
        self.disable_duet = tk.BooleanVar()
        self.disable_stitch = tk.BooleanVar()
        self.brand_content = tk.BooleanVar()
        self.brand_organic = tk.BooleanVar()
        self.ai_generated = tk.BooleanVar()
        self.consent = tk.BooleanVar()

        ttk.Label(frame, text="Video file", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.video_path).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(frame, text="Browse…", command=self.browse_video).grid(row=1, column=1, padx=(8, 0), pady=(6, 0))

        ttk.Label(frame, text="Caption", style="Section.TLabel").grid(row=2, column=0, sticky="w", pady=(18, 6))
        self.caption = tk.Text(frame, height=7, wrap="word")
        self.caption.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self.caption.bind("<KeyRelease>", lambda _event: self._update_caption_count())
        self.caption_count = ttk.Label(frame, text="0 / 2200")
        self.caption_count.grid(row=4, column=1, sticky="e", pady=(4, 0))

        options = ttk.Frame(frame)
        options.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Label(options, text="Privacy").grid(row=0, column=0, sticky="w")
        self.privacy_combo = ttk.Combobox(options, textvariable=self.privacy, state="readonly", width=30)
        self.privacy_combo["values"] = ("SELF_ONLY",)
        self.privacy_combo.grid(row=1, column=0, sticky="w", pady=(4, 10))
        ttk.Label(options, text="Local publish date (optional, YYYY-MM-DD HH:MM)").grid(
            row=0, column=1, sticky="w", padx=(22, 0)
        )
        ttk.Entry(options, textvariable=self.publish_at, width=28).grid(
            row=1, column=1, sticky="w", padx=(22, 0), pady=(4, 10)
        )

        checks = ttk.Frame(frame)
        checks.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.comment_check = ttk.Checkbutton(checks, text="Disable comments", variable=self.disable_comment)
        self.duet_check = ttk.Checkbutton(checks, text="Disable Duet", variable=self.disable_duet)
        self.stitch_check = ttk.Checkbutton(checks, text="Disable Stitch", variable=self.disable_stitch)
        self.comment_check.grid(row=0, column=0, sticky="w", padx=(0, 18))
        self.duet_check.grid(row=0, column=1, sticky="w", padx=(0, 18))
        self.stitch_check.grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(checks, text="Paid partnership", variable=self.brand_content).grid(
            row=1, column=0, sticky="w", pady=(8, 0), padx=(0, 18)
        )
        ttk.Checkbutton(checks, text="Promotes own business", variable=self.brand_organic).grid(
            row=1, column=1, sticky="w", pady=(8, 0), padx=(0, 18)
        )
        ttk.Checkbutton(checks, text="AI-generated content", variable=self.ai_generated).grid(
            row=1, column=2, sticky="w", pady=(8, 0)
        )

        ttk.Checkbutton(
            frame,
            text="I reviewed this video and explicitly authorize the app to send it to TikTok.",
            variable=self.consent,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(18, 10))

        self.progress = ttk.Progressbar(frame, maximum=100)
        self.progress.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        buttons = ttk.Frame(frame)
        buttons.grid(row=9, column=0, columnspan=2, sticky="w")
        self.publish_button = ttk.Button(buttons, text="Publish now", style="Accent.TButton", command=self.publish_now)
        self.publish_button.pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Schedule locally", command=self.schedule_local).pack(side="left")
        self.publish_status = tk.StringVar(value="Ready.")
        ttk.Label(frame, textvariable=self.publish_status, wraplength=720).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(14, 0)
        )
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

    def _build_queue_tab(self) -> None:
        frame = self.queue_tab
        columns = ("id", "scheduled", "video", "status", "publish_id")
        self.queue_tree = ttk.Treeview(frame, columns=columns, show="headings", height=18)
        labels = {"id": "ID", "scheduled": "Scheduled", "video": "Video", "status": "Status", "publish_id": "Publish ID"}
        widths = {"id": 50, "scheduled": 170, "video": 280, "status": 100, "publish_id": 170}
        for column in columns:
            self.queue_tree.heading(column, text=labels[column])
            self.queue_tree.column(column, width=widths[column], anchor="w")
        self.queue_tree.pack(fill="both", expand=True)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Refresh", command=self.refresh_queue).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Publish due jobs", command=self.run_due).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Delete selected", command=self.delete_selected_job).pack(side="left")

    def _build_log_tab(self) -> None:
        self.log_text = tk.Text(self.log_tab, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def _load_settings(self) -> None:
        settings = self.service.settings()
        self.client_key.set(settings.client_key)
        self.redirect_uri.set(settings.redirect_uri)
        self.timezone_name.set(settings.timezone)
        self.refresh_queue()
        if self.service.store.get_secret(settings.client_key, "access_token"):
            self.connection_status.set("Token stored — refresh creator info")

    def save_settings(self) -> None:
        try:
            self.service.save_configuration(
                self.client_key.get(),
                self.client_secret.get(),
                self.redirect_uri.get(),
                self.timezone_name.get(),
            )
            self.log("Settings saved locally.")
        except Exception as exc:
            messagebox.showerror("Settings", str(exc))

    def connect(self) -> None:
        settings = self.service.settings()
        if not settings.client_key:
            self.tabs.select(self.settings_tab)
            messagebox.showerror("Configuration", "Configure the TikTok app credentials in Settings first.")
            return
        self._run_background("connect", self.service.connect)

    def disconnect(self) -> None:
        if not messagebox.askyesno("Disconnect", "Revoke TikTok access and remove local tokens?"):
            return
        self._run_background("disconnect", self.service.disconnect)

    def refresh_creator(self) -> None:
        self._run_background("creator", self.service.creator_info)

    def browse_video(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose a video",
            filetypes=[("Videos", "*.mp4 *.mov *.webm"), ("All files", "*")],
        )
        if selected:
            self.video_path.set(selected)

    def _payload(self) -> dict:
        video = Path(self.video_path.get()).expanduser()
        if not video.is_file():
            raise ValueError("Choose an existing video file.")
        caption = self.caption.get("1.0", "end-1c")
        if utf16_length(caption) > 2200:
            raise ValueError("Caption exceeds 2200 UTF-16 units.")
        if not self.consent.get():
            raise ValueError("You must explicitly authorize the export.")
        return {
            "video": str(video.resolve()),
            "caption": caption,
            "privacy_level": self.privacy.get(),
            "disable_comment": self.disable_comment.get(),
            "disable_duet": self.disable_duet.get(),
            "disable_stitch": self.disable_stitch.get(),
            "brand_content_toggle": self.brand_content.get(),
            "brand_organic_toggle": self.brand_organic.get(),
            "is_aigc": self.ai_generated.get(),
            "consent": True,
        }

    def publish_now(self) -> None:
        try:
            payload = self._payload()
        except Exception as exc:
            messagebox.showerror("Publish", str(exc))
            return
        self.progress["value"] = 0
        self.publish_status.set("Publishing…")
        self._run_background(
            "publish",
            lambda: self.service.publish(payload, progress=self._progress_callback, wait=True),
        )

    def schedule_local(self) -> None:
        try:
            payload = self._payload()
            value = self.publish_at.get().strip()
            if not value:
                raise ValueError("Enter a future local publish date.")
            timezone = ZoneInfo(self.timezone_name.get().strip())
            scheduled = datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=timezone)
            if scheduled <= datetime.now(timezone):
                raise ValueError("Scheduled date must be in the future.")
            result = self.service.schedule(scheduled, payload)
            self.publish_status.set(json.dumps(result, ensure_ascii=False))
            self.refresh_queue()
        except Exception as exc:
            messagebox.showerror("Schedule", str(exc))

    def run_due(self) -> None:
        self._run_background("due", lambda: self.service.run_due(wait=True))

    def refresh_queue(self) -> None:
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
        for job in self.service.queue.list():
            payload = job["payload"]
            self.queue_tree.insert(
                "",
                "end",
                iid=str(job["id"]),
                values=(
                    job["id"],
                    job["scheduled_at"],
                    Path(payload.get("video", "")).name,
                    job["status"],
                    job["publish_id"],
                ),
            )

    def delete_selected_job(self) -> None:
        selected = self.queue_tree.selection()
        if not selected:
            return
        for item in selected:
            self.service.queue.delete(int(item))
        self.refresh_queue()

    def _update_caption_count(self) -> None:
        count = utf16_length(self.caption.get("1.0", "end-1c"))
        self.caption_count.configure(text=f"{count} / 2200")

    def _progress_callback(self, sent: int, total: int) -> None:
        self.events.put(("progress", (sent, total)))

    def _run_background(self, action: str, function) -> None:
        def worker():
            try:
                result = function()
                self.events.put((f"result:{action}", result))
            except Exception as exc:
                self.events.put((f"error:{action}", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_events(self) -> None:
        while True:
            try:
                event, value = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "log":
                self._append_log(str(value))
            elif event == "progress":
                sent, total = value
                self.progress["value"] = (sent / total) * 100 if total else 0
            elif event.startswith("error:"):
                action = event.split(":", 1)[1]
                self.publish_status.set(f"{action} failed: {value}")
                messagebox.showerror("TikTok Desktop Publisher", str(value))
            elif event == "result:connect" or event == "result:creator":
                self._display_creator(value)
            elif event == "result:disconnect":
                self.connection_status.set("Not connected")
                self.creator_summary.set("No creator information loaded.")
            elif event == "result:publish":
                self.progress["value"] = 100
                self.publish_status.set(json.dumps(value, ensure_ascii=False))
                messagebox.showinfo("TikTok", "Video sent to TikTok. Processing status is shown below.")
            elif event == "result:due":
                self.publish_status.set(json.dumps(value, ensure_ascii=False))
                self.refresh_queue()
        self.after(100, self._drain_events)

    def _display_creator(self, creator) -> None:
        self.creator = creator
        self.connection_status.set(f"Connected: {creator.creator_nickname or creator.creator_username}")
        self.creator_summary.set(
            f"Nickname: {creator.creator_nickname}\n"
            f"Username: {creator.creator_username}\n"
            f"Available privacy: {', '.join(creator.privacy_level_options)}\n"
            f"Maximum video duration: {creator.max_video_post_duration_sec}s"
        )
        values = creator.privacy_level_options or ["SELF_ONLY"]
        self.privacy_combo["values"] = values
        if self.privacy.get() not in values:
            self.privacy.set("SELF_ONLY" if "SELF_ONLY" in values else values[0])
        self._apply_interaction_restriction(self.comment_check, self.disable_comment, creator.comment_disabled)
        self._apply_interaction_restriction(self.duet_check, self.disable_duet, creator.duet_disabled)
        self._apply_interaction_restriction(self.stitch_check, self.disable_stitch, creator.stitch_disabled)

    @staticmethod
    def _apply_interaction_restriction(widget, variable, disabled_by_creator: bool) -> None:
        if disabled_by_creator:
            variable.set(True)
            widget.state(["disabled"])
        else:
            widget.state(["!disabled"])

    def log(self, message: str) -> None:
        self.events.put(("log", message))

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{datetime.now():%H:%M:%S}  {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


def main() -> None:
    app = PublisherGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
