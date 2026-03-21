# utils/cpu_job_object.py
"""Windows Job Object CPU rate limiting.

Uses the Windows kernel's JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP to enforce
an exact CPU usage ceiling on a process and all its children.  All cores
stay active; each is limited to the specified percentage.

On non-Windows platforms, the functions are safe no-ops.
"""

import ctypes
import ctypes.wintypes
import logging
import sys

logger = logging.getLogger(__name__)


# ── Public API ──────────────────────────────────────────────────────────────

def apply_cpu_limit(pid: int, cpu_pct: int, rate_correction: float = 0.90):
    """Apply a hard CPU % cap to a process via a Windows Job Object.

    Creates a Job Object with JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
    assigns the process to it, and returns the job handle.

    The handle MUST be kept alive (stored in a variable) for the duration
    of the process.  When closed via release_job(), the cap is removed.

    Child processes spawned by *pid* inherit the cap automatically
    (Windows 8+ nested-job support).

    Args:
        pid:             Target process ID.
        cpu_pct:         User-visible CPU limit (1–100).
        rate_correction: Multiplier applied to cpu_pct before passing to the
                         kernel cap. FFmpeg bursts cause the kernel to overshoot
                         the nominal value; this compensates so the effective
                         average matches the user's intent.  Range: 0.10–1.00.

    Returns the job handle, or None on failure / non-Windows.
    """
    if sys.platform != "win32":
        logger.debug("cpu_job_object: not on Windows, skipping")
        return None

    if not (1 <= cpu_pct <= 100):
        logger.warning("cpu_job_object: invalid cpu_pct=%d, skipping", cpu_pct)
        return None

    if cpu_pct == 100:
        # 100% means no limit; skip the overhead of creating a job object.
        return None

    rate_correction = max(0.10, min(1.00, float(rate_correction)))
    return _win_apply(pid, cpu_pct, rate_correction)


def release_job(handle) -> None:
    """Close the Job Object handle, releasing the CPU cap."""
    if handle is None:
        return
    if sys.platform != "win32":
        return
    try:
        _kernel32().CloseHandle(handle)
    except Exception as exc:
        logger.warning("cpu_job_object: CloseHandle failed: %s", exc)


# ── Windows internals ──────────────────────────────────────────────────────

def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


# Windows constants
_JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
_JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4
_JobObjectCpuRateControlInformation = 15
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_INFORMATION = 0x0200
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000



class _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
    """Minimal binding for JOBOBJECT_CPU_RATE_CONTROL_INFORMATION.

    The union has CpuRate / Weight / MinRate+MaxRate members;
    we only need CpuRate so a flat struct suffices.
    """
    _fields_ = [
        ("ControlFlags", ctypes.wintypes.DWORD),
        ("CpuRate", ctypes.wintypes.DWORD),
    ]


def _win_apply(pid: int, cpu_pct: int, rate_correction: float):
    """Internal: create job, set rate, assign process. Returns handle or None."""
    k32 = _kernel32()

    # Step 1: Create an anonymous Job Object.
    h_job = k32.CreateJobObjectW(None, None)
    if not h_job:
        logger.warning(
            "cpu_job_object: CreateJobObjectW failed (err=%d)",
            ctypes.get_last_error(),
        )
        return None

    # Step 2: Set CPU rate control — hard cap at `cpu_pct` percent.
    # Apply correction factor: bursty FFmpeg workloads overshoot the kernel
    # cap by ~10-13%.  rate_correction compensates so that the user's
    # target (e.g. 80%) is the effective average, not the kernel ceiling.
    effective_rate = max(100, int(cpu_pct * 100 * rate_correction))
    info = _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
    info.ControlFlags = (
        _JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | _JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
    )
    info.CpuRate = effective_rate  # e.g. 80% * 0.90 * 100 = 7200 hundredths
    logger.debug(
        "cpu_job_object: user target=%d%% -> kernel rate=%d (%.1f%%)",
        cpu_pct, effective_rate, effective_rate / 100,
    )

    ok = k32.SetInformationJobObject(
        h_job,
        _JobObjectCpuRateControlInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        err = ctypes.get_last_error()
        logger.warning(
            "cpu_job_object: SetInformationJobObject failed (err=%d)", err,
        )
        k32.CloseHandle(h_job)
        return None

    # Step 3: Open the target process with rights for job assignment + priority.
    h_proc = k32.OpenProcess(
        _PROCESS_SET_QUOTA | _PROCESS_TERMINATE | _PROCESS_SET_INFORMATION,
        False, pid,
    )
    if not h_proc:
        err = ctypes.get_last_error()
        logger.warning(
            "cpu_job_object: OpenProcess(pid=%d) failed (err=%d)", pid, err,
        )
        k32.CloseHandle(h_job)
        return None

    # Step 4: Assign the process to the job.
    ok = k32.AssignProcessToJobObject(h_job, h_proc)
    if not ok:
        err = ctypes.get_last_error()
        logger.warning(
            "cpu_job_object: AssignProcessToJobObject(pid=%d) failed (err=%d)",
            pid, err,
        )
        k32.CloseHandle(h_proc)
        k32.CloseHandle(h_job)
        return None

    # Step 5: Lower process priority to BELOW_NORMAL.
    # Combined with the hard cap, this makes the scheduler less aggressive
    # about giving CPU time, tightening the effective cap.
    ok = k32.SetPriorityClass(h_proc, _BELOW_NORMAL_PRIORITY_CLASS)
    if not ok:
        logger.debug(
            "cpu_job_object: SetPriorityClass(pid=%d) failed (err=%d); "
            "job cap still active",
            pid, ctypes.get_last_error(),
        )

    k32.CloseHandle(h_proc)

    logger.info(
        "cpu_job_object: applied %d%% hard CPU cap + BELOW_NORMAL priority "
        "to PID %d (and children)",
        cpu_pct, pid,
    )
    return h_job
