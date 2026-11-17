"""
Files printed on the office printer (the HP), from the web UI's Docs tab.

Uploads are queued here and printed one at a time by a background worker.
It is a separate queue from print_queue.py, so a long document never holds
up labels, and nothing here touches the label printer.

A job goes:  queued → converting (office files only) → printing → sent → done
             and can end failed or cancelled instead.

  converting  Word / Excel / PowerPoint / text → PDF with LibreOffice.
  printing    each page is drawn as a bitmap (PDFium for PDFs, Pillow for
              photos) through Windows GDI, so any installed printer driver
              works and no PDF reader is needed on the shop computer.
  sent        the job is in the Windows print queue. It is followed there
              until the printer has taken it, and the Docs tab shows why it
              is waiting if it is not printing.

Sleep. A Wi-Fi printer that has gone to sleep can miss jobs or answer late,
and Windows then marks it offline. So before each job the worker knocks on
the printer (a TCP connect to its print port, the same connection a job
opens) until it answers, for up to WAKE_WAIT_S, and a keep-alive thread
knocks every `doc_keepalive_minutes` so the connection stays in use and the
Docs tab knows when the printer stopped answering. A job is sent to Windows
even if the printer never answers: Windows keeps it and prints it as soon as
the printer is back. Nothing here can switch on a printer that has shut
itself down, which is why the README sets Shut Down After Inactivity to Never.
"""

import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
import winreg
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import pypdfium2 as pdfium
import pywintypes
import win32con
import win32gui
import win32print
from PIL import Image, ImageOps, ImageSequence, ImageWin

from printer import PRINTER_NAME as LABEL_PRINTER
from settings_manager import get_doc_settings

_log = logging.getLogger(__name__)

# ── Limits ────────────────────────────────────
MAX_UPLOAD_MB = 25
MAX_COPIES    = 99
MAX_PAGES     = 300   # per file: one bigger than this is almost always the wrong file
MAX_WAITING   = 10    # files queued or printing at once
RENDER_DPI    = 300   # pages are drawn at this resolution, or the printer's if lower
WAKE_WAIT_S   = 45    # how long to knock on a sleeping printer before sending anyway
CONVERT_TIMEOUT_S = 180
KEEP_FINISHED = 20    # finished jobs kept for the Docs tab's list

# ── File types ────────────────────────────────
PDF_TYPES    = {".pdf"}
IMAGE_TYPES  = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
OFFICE_TYPES = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                ".odt", ".ods", ".odp", ".rtf", ".txt", ".csv"}

WORK_DIR   = os.path.join(tempfile.gettempdir(), "srt-docs")
LO_PROFILE = os.path.join(WORK_DIR, "lo-profile")   # LibreOffice's own profile, kept between jobs

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class DocError(Exception):
    """A failure to show the user as it is (unsupported file, damaged file, no printer)."""


class _Cancelled(Exception):
    pass


def file_kind(filename: str) -> Optional[str]:
    """'pdf', 'image' or 'office' from the file name, or None if it can't be printed."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in PDF_TYPES:
        return "pdf"
    if ext in IMAGE_TYPES:
        return "image"
    if ext in OFFICE_TYPES:
        return "office"
    return None


# The keep-alive and the Docs tab's polls read these settings every few
# seconds. Each read opens settings.json, and on Windows a file one process
# holds open makes the other's save fail (see print_queue.py), so they are
# kept here and read again only once a minute, or straight after server.py
# saves them (settings_changed). Only the web UI changes them.
_settings = {"value": None, "at": 0.0}


def _doc_settings() -> dict:
    if _settings["value"] is None or time.time() - _settings["at"] > 60:
        _settings.update(value=get_doc_settings(), at=time.time())
    return _settings["value"]


def settings_changed():
    """Call after saving the document printer settings, so they apply at once."""
    _settings["value"] = None


def _clean_name(filename: str) -> str:
    """The upload's own name, for display and the Windows queue only (never a path)."""
    name = os.path.basename(str(filename or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return (name or "document")[:120]


# ── Printers ──────────────────────────────────
# Printers that open a dialog or another app on the shop computer would hang
# the worker with nobody there to answer, so they are never offered.
_DIALOG_PORTS = {"PORTPROMPT:", "FILE:"}
_DIALOG_NAMES = re.compile(r"onenote|fax", re.I)
_HP = re.compile(r"\bHP\b|hewlett", re.I)


def list_printers() -> list:
    """Printers the Docs tab can use: [{'name', 'driver', 'port'}], label printer left out."""
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        found = win32print.EnumPrinters(flags, None, 2)
    except pywintypes.error:
        _log.exception("Could not list printers")
        return []
    out = []
    for p in found:
        name = p.get("pPrinterName") or ""
        port = (p.get("pPortName") or "").strip()
        if (not name or name == LABEL_PRINTER or port.upper() in _DIALOG_PORTS
                or _DIALOG_NAMES.search(name)):
            continue
        out.append({"name": name, "driver": p.get("pDriverName") or "", "port": port})
    return out


def _auto_printer(printers) -> Optional[str]:
    """The first HP printer: what 'automatic' prints on."""
    for p in printers:
        if _HP.search(p["name"]) or _HP.search(p["driver"]):
            return p["name"]
    return None


def resolve_printer():
    """(printer name or None, chosen automatically?, problem in words or None)."""
    wanted = _doc_settings()["doc_printer"]
    printers = list_printers()
    if wanted:
        if any(p["name"] == wanted for p in printers):
            return wanted, False, None
        return None, False, (f"'{wanted}' is not installed on the shop computer. "
                             "Pick the printer in Settings → Document Printer.")
    auto = _auto_printer(printers)
    if auto:
        return auto, True, None
    return None, True, ("No HP printer is installed on the shop computer. Add it in Windows "
                        "(Printers & scanners), or pick another one in Settings → Document Printer.")


def printer_choices() -> dict:
    """For the Settings picker: every usable printer's name, and the one 'automatic' would use."""
    printers = list_printers()
    return {"printers": [p["name"] for p in printers], "auto": _auto_printer(printers)}


def check_printer_choice(name: str) -> Optional[str]:
    """Why `name` can't be the document printer, or None if it can. Blank means automatic."""
    name = (name or "").strip()
    if not name:
        return None
    if name == LABEL_PRINTER:
        return "That is the label printer. Pick the office printer for documents."
    if not any(p["name"] == name for p in list_printers()):
        return f"'{name}' is not a printer the shop computer can print documents on."
    return None


# ── Where the printer is on the network ───────
_TCPIP_PORTS = r"SYSTEM\CurrentControlSet\Control\Print\Monitors\Standard TCP/IP Port\Ports"


def port_info(port_name: str) -> dict:
    """
    What the printer's Windows port says about reaching it:
    kind ('tcpip' | 'wsd' | 'ipp' | 'usb' | 'other'), host, port, and
    whether Windows polls it with SNMP (None when that does not apply).
    """
    port_name = (port_name or "").split(",")[0].strip()
    info = {"port_name": port_name, "kind": "other", "host": None, "port": None, "snmp": None}
    upper = port_name.upper()
    if not port_name:
        return info
    if upper.startswith("WSD"):
        info["kind"] = "wsd"
        return info
    if upper.startswith(("USB", "LPT", "COM", "DOT4")):
        info["kind"] = "usb"
        return info
    if re.match(r"https?://", port_name, re.I):
        url = urlparse(port_name)
        info.update(kind="ipp", host=url.hostname,
                    port=url.port or (443 if url.scheme.lower() == "https" else 80))
        return info
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _TCPIP_PORTS + "\\" + port_name) as key:
            def value(name, default=None):
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except OSError:
                    return default
            host = str(value("HostName") or "").strip() or str(value("IPAddress") or "").strip()
            lpr = value("Protocol", 1) == 2
            info.update(kind="tcpip", host=host or None,
                        port=515 if lpr else int(value("PortNumber", 9100) or 9100),
                        snmp=bool(value("SNMP Enabled", 0)))
            return info
    except OSError:
        pass
    # Another vendor's TCP/IP monitor, with the address in the port name (IP_192.168.1.20)
    m = re.search(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])", port_name)
    if m:
        info.update(kind="tcpip", host=m.group(1))
    return info


def _knock(host: str, ports, timeout: float = 2.5) -> Optional[int]:
    """The first of `ports` that accepts a connection on `host`, or None. Sends nothing."""
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return port
        except OSError:
            continue
    return None


def _knock_ports(pinfo) -> list:
    """Its own print port first, then the usual ones (raw, IPP, its web page)."""
    ports = [pinfo["port"]] if pinfo.get("port") else []
    return ports + [p for p in (9100, 631, 80) if p not in ports]


# ── Windows printer and job state ─────────────
_ATTR_WORK_OFFLINE = 0x00000400

_ST = win32print
_FAULTS = [   # (status bit, message), the first that is set wins
    (_ST.PRINTER_STATUS_PAUSED,            "Paused in Windows. Resume it in Printers & scanners."),
    (_ST.PRINTER_STATUS_PAPER_JAM,         "Paper jam."),
    (_ST.PRINTER_STATUS_PAPER_OUT,         "Out of paper."),
    (_ST.PRINTER_STATUS_NO_TONER,          "Out of toner."),
    (_ST.PRINTER_STATUS_DOOR_OPEN,         "A door or cover is open."),
    (_ST.PRINTER_STATUS_OUTPUT_BIN_FULL,   "The output tray is full."),
    (_ST.PRINTER_STATUS_USER_INTERVENTION, "The printer needs attention: check its screen."),
    (_ST.PRINTER_STATUS_ERROR,             "Printer error: check its screen."),
]
_ST_OFFLINE = (_ST.PRINTER_STATUS_OFFLINE | _ST.PRINTER_STATUS_NOT_AVAILABLE
               | _ST.PRINTER_STATUS_SERVER_UNKNOWN)

_JOB_DONE    = win32print.JOB_STATUS_PRINTED | win32print.JOB_STATUS_COMPLETE
_JOB_DELETED = win32print.JOB_STATUS_DELETING | win32print.JOB_STATUS_DELETED
_JOB_STUCK   = win32print.JOB_STATUS_ERROR | win32print.JOB_STATUS_OFFLINE | win32print.JOB_STATUS_BLOCKED_DEVQ

WAITING_TEXT = ("Waiting for the printer. It isn't answering: asleep, switched off or off Wi-Fi. "
                "It prints as soon as the printer is back.")


def _windows_state(printer: str) -> dict:
    """GetPrinter level 2 for `printer`, or {} if Windows can't open it."""
    try:
        h = win32print.OpenPrinter(printer)
        try:
            return win32print.GetPrinter(h, 2)
        finally:
            win32print.ClosePrinter(h)
    except pywintypes.error:
        return {}


def _spool_state(printer: str, spool_id: int, reachable: Optional[bool]):
    """
    ('gone' | 'deleted' | 'waiting', detail) for a job in the Windows queue.
    'gone' means the printer has taken all of it.
    """
    try:
        h = win32print.OpenPrinter(printer)
    except pywintypes.error:
        return "waiting", "Can't read the Windows print queue."
    try:
        try:
            info = win32print.GetJob(h, spool_id, 1)
        except pywintypes.error:
            return "gone", ""
    finally:
        win32print.ClosePrinter(h)
    status = info.get("Status", 0) or 0
    if status & _JOB_DONE:
        return "gone", ""
    if status & _JOB_DELETED:
        return "deleted", ""
    if status & win32print.JOB_STATUS_PAPEROUT:
        return "waiting", "The printer is out of paper. Load paper and it carries on."
    if status & win32print.JOB_STATUS_USER_INTERVENTION:
        return "waiting", "The printer needs attention (paper jam, door open or toner). Check its screen."
    if status & win32print.JOB_STATUS_PAUSED:
        return "waiting", "Paused in the Windows print queue."
    if status & _JOB_STUCK or reachable is False:
        return "waiting", WAITING_TEXT
    if status & win32print.JOB_STATUS_PRINTING:
        return "waiting", "Printing…"
    if status & win32print.JOB_STATUS_SPOOLING:
        return "waiting", "Handing it to Windows…"
    ahead = max(0, (info.get("Position") or 1) - 1)
    return "waiting", ("In the Windows print queue" + (f", {ahead} ahead of it." if ahead else "."))


# ── Pages ─────────────────────────────────────
class _PdfPages:
    """A PDF's pages. Its sizes are in inches."""
    fit = False   # shrink a page that is too big for the paper, never enlarge one

    def __init__(self, path):
        try:
            self.pdf = pdfium.PdfDocument(path)
        except pdfium.PdfiumError as e:
            if "password" in str(e).lower():
                raise DocError("This PDF is password-protected. Remove the password and upload it again.")
            raise DocError("Couldn't read this PDF. It may be damaged.")
        self.pdf.init_forms()   # so filled-in form fields print with their values

    def __len__(self):
        return len(self.pdf)

    def size(self, i):
        w, h = self.pdf.get_page_size(i)
        return w / 72, h / 72

    def render(self, i, px_w, px_h, rotate, gray):
        page = self.pdf[i]
        try:
            w_pt, h_pt = page.get_size()
            # px_w is the drawn width, which is the page's height when it is turned
            scale = px_w / (h_pt if rotate else w_pt)
            bitmap = page.render(scale=scale, rotation=270 if rotate else 0,
                                 grayscale=gray, optimize_mode="print", may_draw_forms=True)
            img = bitmap.to_pil()
            return img if gray else img.convert("RGB")
        finally:
            page.close()

    def close(self):
        self.pdf.close()


class _ImagePages:
    """A photo, or each page of a multi-page TIFF. Fitted to the paper."""
    fit = True

    def __init__(self, path):
        try:
            img = Image.open(path)
            frames = ImageSequence.Iterator(img) if img.format == "TIFF" else [img]
            self.frames = [ImageOps.exif_transpose(f.copy()) for f in frames]
        except (OSError, ValueError, Image.DecompressionBombError):
            raise DocError("Couldn't open this picture. It may be damaged, or a type this "
                           "printer can't take: save it as JPG or PDF.")

    def __len__(self):
        return len(self.frames)

    def size(self, i):
        w, h = self.frames[i].size
        return w / RENDER_DPI, h / RENDER_DPI   # only the shape matters: it is fitted

    def render(self, i, px_w, px_h, rotate, gray):
        img = self.frames[i]
        if img.mode in ("RGBA", "LA", "P", "PA"):
            img = img.convert("RGBA")
            flat = Image.new("RGBA", img.size, "white")
            flat.alpha_composite(img)
            img = flat
        img = img.convert("L" if gray else "RGB")
        if rotate:
            img = img.transpose(Image.Transpose.ROTATE_90)   # anticlockwise, like the PDFs
        if img.width > px_w or img.height > px_h:
            img = img.resize((px_w, px_h), Image.Resampling.LANCZOS)
        return img

    def close(self):
        self.frames = []


_CAPS = {"HORZRES": 8, "VERTRES": 10, "LOGPIXELSX": 88, "LOGPIXELSY": 90,
         "PHYSICALWIDTH": 110, "PHYSICALHEIGHT": 111,
         "PHYSICALOFFSETX": 112, "PHYSICALOFFSETY": 113}


def _layout(caps, w_in, h_in, fit, render_dpi):
    """
    Where a page of w_in × h_in inches goes on the sheet:
    (turn it a quarter?, device rectangle, bitmap size to draw it at).
    A landscape page on portrait paper is turned to fill it, and every page
    is centred on the sheet and kept inside the printable area.
    """
    hres, vres = caps["HORZRES"], caps["VERTRES"]
    w_in, h_in = max(w_in, 0.01), max(h_in, 0.01)
    rotate = (w_in > h_in) != (hres > vres)
    if rotate:
        w_in, h_in = h_in, w_in
    nat_w, nat_h = w_in * caps["LOGPIXELSX"], h_in * caps["LOGPIXELSY"]
    s = min(hres / nat_w, vres / nat_h)
    if not fit:
        s = min(s, 1.0)
    tw, th = max(1, round(nat_w * s)), max(1, round(nat_h * s))
    x = (caps["PHYSICALWIDTH"] - tw) // 2 - caps["PHYSICALOFFSETX"]
    y = (caps["PHYSICALHEIGHT"] - th) // 2 - caps["PHYSICALOFFSETY"]
    x, y = max(0, min(x, hres - tw)), max(0, min(y, vres - th))
    px_w = max(1, round(tw * render_dpi / caps["LOGPIXELSX"]))
    px_h = max(1, round(th * render_dpi / caps["LOGPIXELSY"]))
    return rotate, (x, y, x + tw, y + th), (px_w, px_h)


def _printer_dc(printer, copies, pages):
    """
    (DC, times to send the pages, colour?) for `printer`. The driver makes the
    copies itself when it can, collated for a multi-page file; otherwise the
    pages are sent once per copy.
    """
    h = win32print.OpenPrinter(printer)
    try:
        info = win32print.GetPrinter(h, 2)
        port = info.get("pPortName") or ""
        dm = info.get("pDevMode")
        loops = copies
        if dm is not None:
            most = win32print.DeviceCapabilities(printer, port, win32con.DC_COPIES) or 1
            collates = win32print.DeviceCapabilities(printer, port, win32con.DC_COLLATE) == 1
            if copies > 1 and most >= copies and (pages == 1 or collates):
                dm.Copies, loops = copies, 1
                dm.Collate = win32con.DMCOLLATE_TRUE
                dm.Fields |= win32con.DM_COPIES | win32con.DM_COLLATE
            else:
                dm.Copies = 1
                dm.Fields |= win32con.DM_COPIES
            win32print.DocumentProperties(0, h, printer, dm, dm,
                                          win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER)
        color = win32print.DeviceCapabilities(printer, port, 32) == 1   # DC_COLORDEVICE
        hdc = win32gui.CreateDC("WINSPOOL", printer, dm)
    finally:
        win32print.ClosePrinter(h)
    return hdc, loops, color


def print_pages(printer, title, pages, copies, progress=None, cancelled=None, output=None) -> int:
    """
    Draw `pages` on `printer` as one Windows print job and return its job id.
    `output` sends it to a file instead (only for drivers that write files,
    used to test the layout). Raises _Cancelled if `cancelled()` turns true.
    """
    hdc, loops, color = _printer_dc(printer, copies, len(pages))
    try:
        caps = {k: win32print.GetDeviceCaps(hdc, v) for k, v in _CAPS.items()}
        render_dpi = min(RENDER_DPI, caps["LOGPIXELSX"])
        spool_id = win32print.StartDoc(hdc, (title, output, None, 0))
        try:
            total, n = len(pages) * loops, 0
            for _ in range(loops):
                for i in range(len(pages)):
                    if cancelled and cancelled():
                        raise _Cancelled()
                    n += 1
                    if progress:
                        progress(n, total)
                    rotate, rect, (px_w, px_h) = _layout(caps, *pages.size(i), pages.fit, render_dpi)
                    img = pages.render(i, px_w, px_h, rotate, gray=not color)
                    win32print.StartPage(hdc)
                    ImageWin.Dib(img).draw(hdc, rect)
                    win32print.EndPage(hdc)
            win32print.EndDoc(hdc)
        except BaseException:
            try:
                win32print.AbortDoc(hdc)
            except pywintypes.error:
                pass
            raise
    finally:
        win32gui.DeleteDC(hdc)
    return spool_id


# ── Office files → PDF ────────────────────────
def find_soffice() -> Optional[str]:
    """LibreOffice's soffice.exe, or None if it is not installed."""
    candidates = []
    for key in (r"SOFTWARE\LibreOffice\UNO\InstallPath",
                r"SOFTWARE\WOW6432Node\LibreOffice\UNO\InstallPath"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                candidates.append(os.path.join(winreg.QueryValueEx(k, "")[0], "soffice.exe"))
        except OSError:
            pass
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            candidates.append(os.path.join(base, "LibreOffice", "program", "soffice.exe"))
    candidates.append(shutil.which("soffice") or "")
    return next((c for c in candidates if c and os.path.isfile(c)), None)


OFFICE_MISSING = ("Word, Excel and PowerPoint files need LibreOffice on the shop computer "
                  "(free from libreoffice.org). PDFs and photos print without it.")


def _kill_tree(proc):
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   capture_output=True, creationflags=_NO_WINDOW)


def convert_to_pdf(src, out_dir, cancelled=None) -> str:
    """Convert an office file to PDF with LibreOffice and return the PDF's path."""
    exe = find_soffice()
    if not exe:
        raise DocError(OFFICE_MISSING)
    os.makedirs(out_dir, exist_ok=True)
    # Its own profile, so it neither waits on nor disturbs a LibreOffice
    # window someone has open on the shop computer, and can be killed safely.
    cmd = [exe, f"-env:UserInstallation={Path(LO_PROFILE).as_uri()}",
           "--headless", "--invisible", "--norestore", "--nologo", "--nolockcheck", "--nodefault",
           "--convert-to", "pdf", "--outdir", out_dir, src]
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    deadline = time.time() + CONVERT_TIMEOUT_S
    while proc.poll() is None:
        if cancelled and cancelled():
            _kill_tree(proc)
            raise _Cancelled()
        if time.time() > deadline:
            _kill_tree(proc)
            raise DocError("Converting this file took too long. Save it as PDF and upload that instead.")
        time.sleep(0.5)
    out = os.path.join(out_dir, Path(src).stem + ".pdf")
    if not os.path.isfile(out) or os.path.getsize(out) == 0:
        raise DocError("Couldn't open this file. It may be damaged or password-protected: "
                       "save it as PDF and upload that instead.")
    return out


# ── Jobs ──────────────────────────────────────
ACTIVE = ("queued", "converting", "printing", "sent")


@dataclass
class DocJob:
    id: str
    name: str            # the file's own name, shown in the Docs tab and the Windows queue
    path: str            # the upload on disk; every file a job writes is removed when it ends
    kind: str            # "pdf" | "image" | "office"
    copies: int
    username: str
    created_at: str
    status: str = "queued"   # queued | converting | printing | sent | done | failed | cancelled
    detail: str = ""         # what it is doing or waiting for, in words
    pages: int = 0
    printer: str = ""
    error: Optional[str] = None
    finished_at: str = ""
    finished_ts: float = 0.0
    spool_id: int = 0        # its Windows print job, once sent
    cancel_requested: bool = False
    files: list = field(default_factory=list)

    def finish(self, status: str):
        self.status = status
        self.finished_at = datetime.now().strftime("%H:%M:%S")
        self.finished_ts = time.time()

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "copies": self.copies,
            "pages": self.pages, "username": self.username, "status": self.status,
            "detail": self.detail, "error": self.error, "printer": self.printer,
            "created_at": self.created_at, "finished_at": self.finished_at,
            "finished_ts": self.finished_ts,
        }


class DocQueue:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: "OrderedDict[str, DocJob]" = OrderedDict()
        # Last knock on the printer: {host, ok, port, checked_at, since}
        self._reach = {"host": None, "ok": None, "port": None, "checked_at": "", "since": ""}
        self._reach_lock = threading.Lock()
        self._knock_lock = threading.Lock()
        self._clear_work_dir()
        threading.Thread(target=self._process_loop, daemon=True, name="doc-worker").start()
        threading.Thread(target=self._keepalive_loop, daemon=True, name="doc-keepalive").start()

    # ── Adding and cancelling ──────────────────
    def add(self, upload, filename: str, copies, username: str):
        """
        Queue an uploaded file. `upload` has .save(path), like Flask's
        FileStorage. Returns (job dict, None) or (None, message).
        """
        name = _clean_name(filename)
        kind = file_kind(name)
        if kind is None:
            return None, ("Can't print this kind of file. Send a PDF, a photo (JPG, PNG), "
                          "or a Word, Excel or PowerPoint file.")
        try:
            copies = int(str(copies).strip())
        except (TypeError, ValueError):
            copies = 0
        if not 1 <= copies <= MAX_COPIES:
            return None, f"Copies must be a whole number from 1 to {MAX_COPIES}"
        if kind == "office" and not find_soffice():
            return None, OFFICE_MISSING
        printer, _, problem = resolve_printer()
        if not printer:
            return None, problem
        with self._lock:
            if sum(j.status in ACTIVE[:3] for j in self._jobs.values()) >= MAX_WAITING:
                return None, f"{MAX_WAITING} files are already waiting to print. Try again when they are done."

        job_id = uuid.uuid4().hex[:8]
        path = os.path.join(WORK_DIR, job_id + os.path.splitext(name)[1].lower())
        try:
            upload.save(path)
            size = os.path.getsize(path)
        except OSError as e:
            _log.exception("Could not save upload %s", name)
            _remove(path)
            return None, f"Couldn't save the file on the shop computer: {e}"
        if size == 0:
            _remove(path)
            return None, "The file is empty."
        if size > MAX_UPLOAD_MB * 1024 * 1024:
            _remove(path)
            return None, f"The file is too large. The limit is {MAX_UPLOAD_MB} MB."

        job = DocJob(id=job_id, name=name, path=path, kind=kind, copies=copies,
                     username=username, created_at=datetime.now().strftime("%H:%M:%S"),
                     printer=printer, files=[path])
        with self._lock:
            self._jobs[job.id] = job
        return job.to_dict(), None

    def cancel(self, job_id: str):
        """(True, message) once the job is cancelled or will stop at the next page, else (False, why)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in ACTIVE:
                return False, "Job not found or already finished"
            if job.status == "queued":
                job.finish("cancelled")
                self._discard_files(job)
                return True, "Cancelled"
            if job.status in ("converting", "printing"):
                job.cancel_requested = True
                return True, "Stopping"
            printer, spool_id = job.printer, job.spool_id
        # Sent: take it out of the Windows queue
        try:
            h = win32print.OpenPrinter(printer)
            try:
                win32print.SetJob(h, spool_id, 0, None, win32print.JOB_CONTROL_DELETE)
            finally:
                win32print.ClosePrinter(h)
        except pywintypes.error as e:
            if e.winerror == 87:   # no such job: the printer has already taken all of it
                with self._lock:
                    if job.status == "sent":
                        job.detail = ""
                        job.finish("done")
                return False, "Too late: it has already gone to the printer"
            return False, f"Windows would not remove it from the print queue: {e.strerror}"
        with self._lock:
            if job.status == "sent":
                job.detail = ""
                job.finish("cancelled")
        return True, "Cancelled"

    def list_all(self) -> list:
        """Every job, newest first, with sent ones brought up to date from the Windows queue."""
        self._refresh_sent()
        with self._lock:
            return [j.to_dict() for j in reversed(self._jobs.values())]

    def active_count(self) -> int:
        with self._lock:
            return sum(j.status in ACTIVE for j in self._jobs.values())

    # ── Printer state ──────────────────────────
    def printer_status(self) -> dict:
        """What the Docs tab shows about the printer, from Windows and the last knock."""
        name, auto, problem = resolve_printer()
        st = {"name": name, "auto": auto, "state": "missing", "online": False,
              "message": problem or "", "host": None, "port_kind": None,
              "reachable": None, "checked_at": "", "since": "", "tips": [],
              "office_ok": find_soffice() is not None}
        if not name:
            return st
        info = _windows_state(name)
        if not info:
            st.update(state="error", message=f"Windows can't open '{name}'. Is it still installed?")
            return st
        pinfo = port_info(info.get("pPortName"))
        st.update(host=pinfo["host"], port_kind=pinfo["kind"])
        if pinfo["kind"] == "wsd":
            st["tips"].append("Windows reaches this printer through a WSD port, which loses it when it "
                              "sleeps. Give it a Standard TCP/IP port: see the README, Document printer.")
        if pinfo["snmp"]:
            st["tips"].append("Untick 'SNMP Status Enabled' on the printer's port in Windows. With it on, "
                              "Windows marks a sleeping printer offline.")
        with self._reach_lock:
            reach = dict(self._reach)
        if pinfo["host"] and reach["host"] == pinfo["host"]:
            st.update(reachable=reach["ok"], checked_at=reach["checked_at"], since=reach["since"])

        status = info.get("Status", 0) or 0
        if info.get("Attributes", 0) & _ATTR_WORK_OFFLINE:
            st.update(state="error", message="Windows has it set to 'Use Printer Offline'. Untick that "
                                             "in Printers & scanners, or nothing prints.")
            return st
        for bit, text in _FAULTS:
            if status & bit:
                st.update(state="error", message=text)
                return st
        if st["reachable"] is False:
            st.update(state="asleep", message="Not answering: asleep, switched off or off Wi-Fi. "
                                              "Files wait and print when it's back.")
        elif st["reachable"] is None and status & _ST_OFFLINE:
            st.update(state="asleep", message="Windows says it's offline. It may be asleep: "
                                              "files wait and print when it's back.")
        else:
            st.update(state="ready", online=True, message="Ready." if st["reachable"] else "Ready, as far as Windows knows.")
        return st

    def check(self, printer: Optional[str] = None, wait_s: float = 0, cancelled=None) -> Optional[bool]:
        """
        Knock on `printer` (default: the document printer) until it answers
        or `wait_s` runs out. Returns True / False, or None when its address
        is unknown (USB or WSD port).
        """
        name = printer or resolve_printer()[0]
        if not name:
            return None
        pinfo = port_info(_windows_state(name).get("pPortName"))
        host = pinfo["host"]
        if not host:
            return None
        deadline = time.time() + wait_s
        with self._knock_lock:
            while True:
                port = _knock(host, _knock_ports(pinfo))
                if port or time.time() >= deadline or (cancelled and cancelled()):
                    break
                time.sleep(min(3, max(0.0, deadline - time.time())))
        self._record(host, port)
        return port is not None

    def _record(self, host, port):
        ok = port is not None
        now = datetime.now()
        with self._reach_lock:
            changed = self._reach["host"] != host or self._reach["ok"] != ok
            self._reach.update(host=host, ok=ok, port=port, checked_at=now.strftime("%H:%M:%S"))
            if changed:
                self._reach["since"] = now.strftime("%d %b %H:%M")
        if changed:
            if ok:
                _log.warning("Document printer at %s is answering (port %s)", host, port)
            else:
                _log.warning("Document printer at %s stopped answering", host)

    # ── Worker ─────────────────────────────────
    def _process_loop(self):
        """Background worker: one file at a time, FIFO. Never lets an error end the thread."""
        while True:
            try:
                job = self._next_queued()
                if job:
                    self._run(job)
                else:
                    self._refresh_sent()
                    time.sleep(1)
            except Exception:
                _log.exception("Document worker hit an error; continuing.")
                time.sleep(2)

    def _next_queued(self) -> Optional[DocJob]:
        with self._lock:
            return next((j for j in self._jobs.values() if j.status == "queued"), None)

    def _set(self, job, status, detail=""):
        with self._lock:
            if job.status in ACTIVE:
                job.status, job.detail = status, detail

    def _run(self, job: DocJob):
        cancelled = lambda: job.cancel_requested
        pages = None
        try:
            path = job.path
            if job.kind == "office":
                self._set(job, "converting", "Converting to PDF…")
                out_dir = os.path.join(WORK_DIR, job.id + "-pdf")
                job.files.append(out_dir)
                path = convert_to_pdf(job.path, out_dir, cancelled)
            self._set(job, "printing", "Opening the file…")
            pages = _ImagePages(path) if job.kind == "image" else _PdfPages(path)
            job.pages = len(pages)
            if job.pages == 0:
                raise DocError("This file has no pages to print.")
            if job.pages > MAX_PAGES:
                raise DocError(f"This file has {job.pages} pages. The limit is {MAX_PAGES} per file.")

            job.detail = "Waking the printer…"
            awake = self.check(job.printer, wait_s=WAKE_WAIT_S, cancelled=cancelled)
            if cancelled():
                raise _Cancelled()
            job.spool_id = print_pages(
                job.printer, job.name, pages, job.copies, cancelled=cancelled,
                progress=lambda n, total: setattr(job, "detail", f"Sending page {n} of {total}…"))
            self._set(job, "sent", WAITING_TEXT if awake is False else "Printing…")
        except _Cancelled:
            with self._lock:
                job.detail = ""
                job.finish("cancelled")
        except DocError as e:
            with self._lock:
                job.error, job.detail = str(e), ""
                job.finish("failed")
        except Exception as e:
            _log.exception("Document job %s (%s) failed", job.id, job.name)
            with self._lock:
                job.error, job.detail = f"Printing failed: {e}", ""
                job.finish("failed")
        finally:
            if pages is not None:
                pages.close()
            # The Windows queue has its own copy once sent, so the upload can go
            self._discard_files(job)
            self._trim()

    def _refresh_sent(self):
        with self._lock:
            sent = [j for j in self._jobs.values() if j.status == "sent"]
        if not sent:
            return
        with self._reach_lock:
            reachable = self._reach["ok"]
        for job in sent:
            state, detail = _spool_state(job.printer, job.spool_id, reachable)
            with self._lock:
                if job.status != "sent":
                    continue
                if state == "gone":
                    job.detail = ""
                    job.finish("done")
                elif state == "deleted":
                    job.detail, job.error = "", "Removed from the Windows print queue."
                    job.finish("cancelled")
                else:
                    job.detail = detail

    def _keepalive_loop(self):
        """Knock on the printer every few minutes (Settings → Document Printer)."""
        last = 0.0
        while True:
            try:
                minutes = _doc_settings()["doc_keepalive_minutes"]
                if minutes and time.time() - last >= minutes * 60:
                    last = time.time()
                    self.check()
            except Exception:
                _log.exception("Printer keep-alive hit an error; continuing.")
            time.sleep(10)

    # ── Files ──────────────────────────────────
    @staticmethod
    def _discard_files(job):
        for path in job.files:
            _remove(path)
        job.files = []

    def _trim(self):
        """Forget all but the latest KEEP_FINISHED finished jobs."""
        with self._lock:
            done = [jid for jid, j in self._jobs.items() if j.status not in ACTIVE]
            for jid in done[:-KEEP_FINISHED]:
                del self._jobs[jid]

    @staticmethod
    def _clear_work_dir():
        """Uploads left by a server that stopped mid-job: their jobs are gone, so are they."""
        os.makedirs(WORK_DIR, exist_ok=True)
        for entry in os.listdir(WORK_DIR):
            if entry != os.path.basename(LO_PROFILE):
                _remove(os.path.join(WORK_DIR, entry))


def _remove(path):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        _log.warning("Could not remove %s", path)


# ── Singleton ─────────────────────────────────
_queue = None
_queue_lock = threading.Lock()


def get_doc_queue() -> DocQueue:
    """The document queue, started on first use (server.py starts it at import)."""
    global _queue
    with _queue_lock:
        if _queue is None:
            _queue = DocQueue()
        return _queue
