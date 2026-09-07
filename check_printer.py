"""
Report what Windows actually says about the label printer.

Run it on the print machine, in the label-bot folder:

    python check_printer.py

It changes nothing. It prints the exact printer name Windows knows, the
raw status integer and every flag set in it, so "offline" stops being a
guess. Paste the whole output back.
"""

import win32print

from printer import PRINTER_NAME, get_printer_status

# winspool PRINTER_STATUS_* values
FLAGS = [
    (0x00000001, "PAUSED"),           (0x00000002, "ERROR"),
    (0x00000004, "PENDING_DELETION"), (0x00000008, "PAPER_JAM"),
    (0x00000010, "PAPER_OUT"),        (0x00000020, "MANUAL_FEED"),
    (0x00000040, "PAPER_PROBLEM"),    (0x00000080, "OFFLINE"),
    (0x00000100, "IO_ACTIVE"),        (0x00000200, "BUSY"),
    (0x00000400, "PRINTING"),         (0x00000800, "OUTPUT_BIN_FULL"),
    (0x00001000, "NOT_AVAILABLE"),    (0x00002000, "WAITING"),
    (0x00004000, "PROCESSING"),       (0x00008000, "INITIALIZING"),
    (0x00010000, "WARMING_UP"),       (0x00020000, "TONER_LOW"),
    (0x00040000, "NO_TONER"),         (0x00080000, "PAGE_PUNT"),
    (0x00100000, "USER_INTERVENTION"),(0x00200000, "OUT_OF_MEMORY"),
    (0x00400000, "DOOR_OPEN"),        (0x00800000, "SERVER_UNKNOWN"),
    (0x01000000, "POWER_SAVE"),
]


def main():
    print("=" * 62)
    print("Printer configured in printer.py: %r" % PRINTER_NAME)
    print("=" * 62)

    print("\nPrinters Windows can see:")
    names = []
    for flags, desc, name, comment in win32print.EnumPrinters(
        win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    ):
        names.append(name)
        mark = "  <-- configured" if name == PRINTER_NAME else ""
        print("   %r%s" % (name, mark))

    if PRINTER_NAME not in names:
        print("\n*** %r is NOT in that list. ***" % PRINTER_NAME)
        print("    Nothing will print until PRINTER_NAME matches one of the")
        print("    names above exactly, including spaces and capitals.")
        return

    print("\nDefault printer: %r" % win32print.GetDefaultPrinter())

    h = win32print.OpenPrinter(PRINTER_NAME)
    try:
        info = win32print.GetPrinter(h, 2)
        status = info["Status"]
        print("\nRaw status integer: %d  (0x%08X)" % (status, status))
        if status == 0:
            print("   no flags set -> READY")
        else:
            for bit, label in FLAGS:
                if status & bit:
                    print("   0x%08X  %s" % (bit, label))

        print("\nPort        : %r" % info.get("pPortName"))
        print("Driver      : %r" % info.get("pDriverName"))
        print("Jobs queued : %s" % info.get("cJobs"))
        attrs = info.get("Attributes", 0)
        print("Attributes  : %d  (WORK_OFFLINE set: %s)"
              % (attrs, bool(attrs & 0x00000400)))

        jobs = win32print.EnumJobs(h, 0, 99)
        if jobs:
            print("\nStuck jobs in the spooler (these block new prints):")
            for j in jobs:
                print("   id=%s  %r  status=%s  submitted=%s"
                      % (j.get("JobId"), j.get("pDocument"),
                         j.get("Status"), j.get("Submitted")))
        else:
            print("\nSpooler queue: empty")
    finally:
        win32print.ClosePrinter(h)

    print("\nWhat the app reports: %s" % get_printer_status())
    print("=" * 62)


if __name__ == "__main__":
    main()
