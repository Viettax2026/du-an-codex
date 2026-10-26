"""Windows also terminates child Node processes if the tool is force-closed."""
import os

_job_handle=None


def protect_process_tree():
    global _job_handle
    if os.name!='nt' or _job_handle:return
    import ctypes
    from ctypes import wintypes
    class BasicLimits(ctypes.Structure):
        _fields_=[('ProcessTime',ctypes.c_int64),('JobTime',ctypes.c_int64),('LimitFlags',wintypes.DWORD),
            ('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),
            ('ActiveProcessLimit',wintypes.DWORD),('Affinity',ctypes.c_size_t),
            ('PriorityClass',wintypes.DWORD),('SchedulingClass',wintypes.DWORD)]
    class Counters(ctypes.Structure):
        _fields_=[(key,ctypes.c_uint64) for key in ['ReadOperations','WriteOperations','OtherOperations','ReadBytes','WriteBytes','OtherBytes']]
    class ExtendedLimits(ctypes.Structure):
        _fields_=[('BasicLimitInformation',BasicLimits),('IoInfo',Counters),('ProcessMemoryLimit',ctypes.c_size_t),
            ('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];kernel.CreateJobObjectW.restype=wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    handle=kernel.CreateJobObjectW(None,None)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    limits=ExtendedLimits();limits.BasicLimitInformation.LimitFlags=0x2000
    if not kernel.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle,kernel.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    # Keep the non-inheritable handle open until this process exits. Closing it
    # then kills every remaining descendant, including a stuck QR/send worker.
    _job_handle=handle
